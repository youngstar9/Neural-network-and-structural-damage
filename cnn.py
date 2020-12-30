#%%
import numpy as np
import tensorflow as tf
import tensorflow.keras.layers as keras
import matplotlib.pyplot as plt
import pickle
from tensorflow import keras
from tensorflow.keras import losses,datasets,layers,optimizers,Sequential, metrics,models

#启用动态图机制
tf.compat.v1.enable_eager_execution()


config = tf.compat.v1.ConfigProto(allow_soft_placement=True)
config.gpu_options.per_process_gpu_memory_fraction = 0.2
tf.compat.v1.keras.backend.set_session(tf.compat.v1.Session(config=config))

TRAIN_SET = 'G:/subject2/accel/class1/train_set.pickle'
TEST_SET = 'G:/subject2/accel/class1/test_set.pickle'

with open(TEST_SET, 'rb') as file:
    test_set = pickle.load(file)
    x_test = test_set['x']
    y_test = test_set['y']

with open(TRAIN_SET, 'rb') as file:
    train_set = pickle.load(file)
    x_train = train_set['x']
    y_train = train_set['y']
    
def parameter_count():
    total = 0
    for v in tf.compat.v1.trainable_variables():
        v_elements = 1
        for dim in v.get_shape().as_list():
            v_elements *= dim

        total += v_elements
    return total


#%%
def combined_dataset(features, labels):
    assert features.shape[0] == labels.shape[0]
    dataset = tf.data.Dataset.from_tensor_slices(({'time_series': features}, labels))
    return dataset

def class_for_element(features, labels):
    return labels

# For training
def train_input_fn():
    dataset = combined_dataset(x_train, y_train)
    return dataset.repeat().shuffle(500000).batch(128).prefetch(1)

# For evaluation and metrics
def eval_input_fn():
    dataset = combined_dataset(x_test, y_test)
    return dataset.batch(64).prefetch(1)


#%%
CNN_MODEL_DIR = 'G:/subject2/accel/class1/Models/CNN-Paper'

def conv_unit(unit, input_layer):
    s = '_' + str(unit)
    layer = tf.keras.layers.Conv1D(name='Conv1' + s, filters=32, kernel_size=5, strides=1, padding='same', activation='relu')(input_layer)
    layer = tf.keras.layers.Conv1D(name='Conv2' + s, filters=32, kernel_size=5, strides=1, padding='same', activation=None)(layer )
    layer = tf.keras.layers.Add(name='ResidualSum' + s)([layer, input_layer])
    layer = tf.keras.layers.Activation("relu", name='Act' + s)(layer)
    layer = tf.keras.layers.MaxPooling1D(name='MaxPool' + s, pool_size=5, strides=2)(layer)
    return layer

def cnn_model(input_layer, mode, params):
    current_layer = tf.keras.layers.Conv1D(filters=32, kernel_size=5, strides=1)(input_layer)

    for i in range(5):
        current_layer = conv_unit(i + 1, current_layer)

    current_layer = tf.keras.layers.Flatten()(current_layer)
    current_layer = tf.keras.layers.Dense(32, name='FC1', activation='relu')(current_layer)
    logits = tf.keras.layers.Dense(5, name='Output')(current_layer)
    
    print('Parameter count:', parameter_count())
    return logits

#%%
# Initial learning rate
INITIAL_LEARNING_RATE = 0.001

# Learning rate decay per LR_DECAY_STEPS steps (1.0 = no decay)
LR_DECAY_RATE = 0.5

# Number of steps for LR to decay by LR_DECAY_RATE
LR_DECAY_STEPS = 4000

# Threshold for gradient clipping
GRADIENT_NORM_THRESH = 10.0

# Select model to train
MODEL_DIR = CNN_MODEL_DIR
MODEL_FN = cnn_model

def classifier_fn(features, labels, mode, params):
    is_training = mode == tf.estimator.ModeKeys.TRAIN
    input_layer = tf.compat.v1.feature_column.input_layer(features, params['feature_columns'])
    input_layer = tf.expand_dims(input_layer, -1)

    logits = MODEL_FN(input_layer, mode, params)

    # For prediction, exit here
    predicted_classes = tf.argmax(logits, 1)
    if mode == tf.estimator.ModeKeys.PREDICT:
        predictions = {
            'class_ids': predicted_classes[:, tf.newaxis],
            'probabilities': tf.nn.softmax(logits),
            'logits': logits,
        }
        return tf.estimator.EstimatorSpec(mode, predictions=predictions)

    # For training and evaluation, compute the loss (MSE)
    loss = tf.compat.v1.losses.sparse_softmax_cross_entropy(labels=labels, logits=logits)

    accuracy = tf.compat.v1.metrics.accuracy(labels=labels, predictions=predicted_classes, name='acc_op')
    metrics = {'accuracy': accuracy}
    tf.summary.scalar('accuracy', accuracy[1])

    if mode == tf.estimator.ModeKeys.EVAL:
        return tf.estimator.EstimatorSpec(mode, loss=loss, eval_metric_ops=metrics)

    # For training...
    global_step = tf.compat.v1.train.get_global_step()
    learning_rate = tf.compat.v1.train.exponential_decay(INITIAL_LEARNING_RATE, global_step, LR_DECAY_STEPS, LR_DECAY_RATE)

    optimizer = tf.compat.v1.train.AdamOptimizer(learning_rate=learning_rate)
    #optimizer = tf.contrib.estimator.clip_gradients_by_norm(optimizer, GRADIENT_NORM_THRESH)
    
    train_op = optimizer.minimize(loss, global_step=tf.compat.v1.train.get_global_step())
    return tf.estimator.EstimatorSpec(mode, loss=loss, train_op=train_op)

#%%
feature_columns = [tf.feature_column.numeric_column('time_series', [1500])]

estimator = tf.estimator.Estimator(
    model_fn=classifier_fn,
    model_dir=MODEL_DIR,
    params={
        'feature_columns': feature_columns,
    })

estimator.train(train_input_fn, steps=10)
info = estimator.evaluate(input_fn=eval_input_fn)

#%%
import sklearn.metrics as skm
import seaborn as sns

dataset_fn = eval_input_fn

predictions = estimator.predict(input_fn=dataset_fn)
y_pred = []
y_prob = []

for i, value in enumerate(predictions):
    class_id = value['class_ids']
    y_pred.append(class_id)
    probabilities = value['probabilities']
    y_prob.append(probabilities[class_id])
del predictions

y_pred = np.array(y_pred)
y_prob = np.array(y_prob)
y_test = np.reshape(y_test, (len(y_test), 1))

# Classification report
report = skm.classification_report(y_test, y_pred)
print(report)

# Confusion matrix
labels = ['A','B','C','D','E']
tick_marks = np.array(range(len(labels))) + 0.5

def plot_confusion_matrix(tp,cm,title='Confusion Matrix',cmap=plt.cm.Blues):
    sns.set(style="darkgrid")
    plt.imshow(cm,interpolation='nearest',cmap=cmap)    #在特定窗口上显示图像
    plt.title(title)  
    plt.colorbar()
    xlocations = np.array(range(len(labels)))
    plt.xticks(xlocations,labels,rotation=90)
    plt.yticks(xlocations,labels)
    plt.ylabel('True label')
    plt.xlabel('Predicted label \n Accuracy={}'.format(tp))

cm = skm.confusion_matrix(y_test,y_pred)
totalt = sum(cm[i][i] for i in range(len(labels)))
totalp = totalt / cm.sum()
np.set_printoptions(precision=3) #输出精度
cm_normalized = cm.astype('float')/cm.sum(axis=1)[:,np.newaxis] #归一化
print(cm_normalized)
plt.figure(figsize=(12,8),dpi=200)

ind_array = np.arange(len(labels))
x, y = np.meshgrid(ind_array, ind_array)

for x_val, y_val in zip(x.flatten(), y.flatten()):
    c = cm_normalized[y_val][x_val]
    if c > 0.01:
        plt.text(x_val, y_val, "%0.3f" % (c,), color='black', fontsize=10, va='center', ha='center')
# offset the tick
plt.gca().set_xticks(tick_marks, minor=True)
plt.gca().set_yticks(tick_marks, minor=True)
plt.gca().xaxis.set_ticks_position('none')
plt.gca().yaxis.set_ticks_position('none')
plt.grid(True, which='minor', linestyle='-')
plt.gcf().subplots_adjust(bottom=0.15)

plot_confusion_matrix(totalp,cm_normalized, title='Normalized confusion matrix')
# show confusion matrix
# plt.savefig(r'G:\Subject\1.1\{}\confusion_matrix.eps'.format(Filepath), format='eps')

plt.show()

y_prob_correct = y_prob[y_pred == y_test]
y_prob_mis = y_prob[y_pred != y_test]

#%%
from astropy.stats import binom_conf_interval

_, _, _ = plt.hist(y_prob, 10, (0, 1))
plt.xlabel('Belief')
plt.ylabel('Count')
plt.title('All Predictions')
plt.show()

n_all, bins = np.histogram(y_prob, 10, (0, 1))
n_correct, bins = np.histogram(y_prob_correct, 10, (0, 1))

f_correct = n_correct / np.clip(n_all, 1, None)
f_bins = 0.5 * (bins[:-1] + bins[1:])

n_correct = n_correct[n_all > 0]
n_total = n_all[n_all > 0]
f_correct = n_correct / n_total
f_bins = f_bins[n_all > 0]

lower_bound, upper_bound = binom_conf_interval(n_correct, n_total)
error_bars = np.array([f_correct - lower_bound, upper_bound - f_correct])

plt.plot([0., 1.], [0., 1.])
plt.errorbar(f_bins, f_correct, yerr=error_bars, fmt='o')
plt.xlabel('Softmax Probability')
plt.ylabel('Frequency')
plt.title('Correct Predictions')
plt.show()
# %%
import seaborn as sns

labels = ['A','B','C','D','E']
tick_marks = np.array(range(len(labels))) + 0.5

def plot_confusion_matrix(tp,cm,title='Confusion Matrix',cmap=plt.cm.Blues):
    sns.set(style="darkgrid")
    plt.imshow(cm,interpolation='nearest',cmap=cmap)    #在特定窗口上显示图像
    plt.title(title)  
    plt.colorbar()
    xlocations = np.array(range(len(labels)))
    plt.xticks(xlocations,labels,rotation=90)
    plt.yticks(xlocations,labels)
    plt.ylabel('True label')
    plt.xlabel('Predicted label \n Accuracy={}'.format(tp))

cm = skm.confusion_matrix(y_test,y_pred)
totalt = sum(cm[i][i] for i in range(len(labels)))
totalp = totalt / cm.sum()
np.set_printoptions(precision=3) #输出精度
cm_normalized = cm.astype('float')/cm.sum(axis=1)[:,np.newaxis] #归一化
print(cm_normalized)
plt.figure(figsize=(12,8),dpi=200)

ind_array = np.arange(len(labels))
x, y = np.meshgrid(ind_array, ind_array)

for x_val, y_val in zip(x.flatten(), y.flatten()):
    c = cm_normalized[y_val][x_val]
    if c > 0.01:
        plt.text(x_val, y_val, "%0.3f" % (c,), color='black', fontsize=10, va='center', ha='center')
# offset the tick
plt.gca().set_xticks(tick_marks, minor=True)
plt.gca().set_yticks(tick_marks, minor=True)
plt.gca().xaxis.set_ticks_position('none')
plt.gca().yaxis.set_ticks_position('none')
plt.grid(True, which='minor', linestyle='-')
plt.gcf().subplots_adjust(bottom=0.15)

plot_confusion_matrix(totalp,cm_normalized, title='Normalized confusion matrix')
# show confusion matrix
# plt.savefig(r'G:\Subject\1.1\{}\confusion_matrix.eps'.format(Filepath), format='eps')

plt.show()

# %%