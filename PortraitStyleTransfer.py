from scipy.misc import imread, imresize, imsave
from scipy.optimize import fmin_l_bfgs_b
import numpy as np
import time
import os
import argparse
import h5py

from keras.models import Sequential
from keras.layers.convolutional import Convolution2D, ZeroPadding2D, AveragePooling2D, MaxPooling2D
from keras import backend as K

parser = argparse.ArgumentParser(description='Neural style transfer with Keras.')
parser.add_argument('base_image_path', metavar='base', type=str,
                    help='Path to the image to transform.')
parser.add_argument('style_reference_image_path', metavar='ref', type=str,
                    help='Path to the style reference image.')
parser.add_argument('result_prefix', metavar='res_prefix', type=str,
                    help='Prefix for the saved results.')

parser.add_argument("--image_size", dest="img_size", default=512, type=int, help='Output Image size')
parser.add_argument("--content_weight", dest="content_weight", default=0.5, type=float, help="Weight of content") # 0.025
parser.add_argument("--style_weight", dest="style_weight", default=0.5, type=float, help="Weight of content") # 1.0
parser.add_argument("--style_scale", dest="style_scale", default=1.0, type=float, help="Scale the weightage of the style") # 1, 0.5, 2
parser.add_argument("--total_variation_weight", dest="tv_weight", default=1e-5, type=float, help="Total Variation in the Weights") # 1.0
parser.add_argument("--num_iter", dest="num_iter", default=10, type=int, help="Number of iterations")
parser.add_argument("--rescale_image", dest="rescale_image", default="True", type=str, help="Rescale image after execution to original dimentions")
parser.add_argument("--rescale_method", dest="rescale_method", default="bilinear", type=str, help="Rescale image algorithm")
parser.add_argument("--maintain_aspect_ratio", dest="maintain_aspect_ratio", default="True", type=str, help="Maintain aspect ratio of image")
parser.add_argument("--content_layer", dest="content_layer", default="conv5_2", type=str, help="Optional 'conv4_2'")
parser.add_argument("--init_image", dest="init_image", default="content", type=str, help="Initial image used to generate the final image. Options are 'content' or 'noise")
parser.add_argument("--pool_type", dest="pool", default="max", type=str, help='Pooling type. Can be "ave" for average pooling or "max" for max pooling ')
parser.add_argument("--g_max", type=float, default=5, help='Clamp - nax')
parser.add_argument("--g_min", type=float, default=0.7, help='Clamp - min')
parser.add_argument("--gamma", type=int, default=100, help='Gamma weight')

args = parser.parse_args()
base_image_path = args.base_image_path
style_reference_image_path = args.style_reference_image_path
result_prefix = args.result_prefix
weights_path = r"vgg16_weights.h5"

def strToBool(v):
    return v.lower() in ("true", "yes", "t", "1")

rescale_image = strToBool(args.rescale_image)
maintain_aspect_ratio = strToBool(args.maintain_aspect_ratio)

# these are the weights of the different loss components
total_variation_weight = args.tv_weight

# dimensions of the generated picture.
img_width = img_height = args.img_size
assert img_height == img_width, 'Due to the use of the Gram matrix, width and height must match.'

img_WIDTH = img_HEIGHT = 0
aspect_ratio = 0
g_max = float(args.g_max)
g_min = float(args.g_min)

# util function to open, resize and format pictures into appropriate tensors
def preprocess_image(image_path, load_dims=False):
    global img_WIDTH, img_HEIGHT, aspect_ratio

    img = imread(image_path, mode="RGB") # Prevents crashes due to PNG images (ARGB)
    if load_dims:
        img_WIDTH = img.shape[0]
        img_HEIGHT = img.shape[1]
        aspect_ratio = img_HEIGHT / img_WIDTH

    img = imresize(img, (img_width, img_height))
    img = img[:, :, ::-1].astype('float64')
    img[:, :, 0] -= 103.939
    img[:, :, 1] -= 116.779
    img[:, :, 2] -= 123.68
    img = img.transpose((2, 0, 1))
    img = np.expand_dims(img, axis=0)
    return img

# util function to convert a tensor into a valid image
def deprocess_image(x):
    x = x.transpose((1, 2, 0))
    x[:, :, 0] += 103.939
    x[:, :, 1] += 116.779
    x[:, :, 2] += 123.68
    x = x[:, :, ::-1]
    x = np.clip(x, 0, 255).astype('uint8')
    return x

# Decide pooling function
pooltype = str(args.pool).lower()
assert pooltype in ["ave", "max"], 'Pooling argument is wrong. Needs to be either "ave" or "max".'

pooltype = 1 if pooltype == "ave" else 0

def pooling_func():
    if pooltype == 1:
        return AveragePooling2D((2, 2), strides=(2, 2))
    else:
        return MaxPooling2D((2, 2), strides=(2, 2))

# get tensor representations of our images
base_image = K.variable(preprocess_image(base_image_path, True))
style_reference_image = K.variable(preprocess_image(style_reference_image_path))

# this will contain our generated image
combination_image = K.placeholder((1, 3, img_width, img_height))

# combine the 3 images into a single Keras tensor
input_tensor = K.concatenate([base_image,
                              style_reference_image,
                              combination_image], axis=0)

# build the VGG16 network with our 3 images as input
first_layer = ZeroPadding2D((1, 1))
first_layer.set_input(input_tensor, shape=(3, 3, img_width, img_height))

model = Sequential()
model.add(first_layer)
model.add(Convolution2D(64, 3, 3, activation='relu', name='conv1_1'))
model.add(ZeroPadding2D((1, 1)))
model.add(Convolution2D(64, 3, 3, activation='relu'))
model.add(pooling_func())

model.add(ZeroPadding2D((1, 1)))
model.add(Convolution2D(128, 3, 3, activation='relu', name='conv2_1'))
model.add(ZeroPadding2D((1, 1)))
model.add(Convolution2D(128, 3, 3, activation='relu'))
model.add(pooling_func())

model.add(ZeroPadding2D((1, 1)))
model.add(Convolution2D(256, 3, 3, activation='relu', name='conv3_1'))
model.add(ZeroPadding2D((1, 1)))
model.add(Convolution2D(256, 3, 3, activation='relu'))
model.add(ZeroPadding2D((1, 1)))
model.add(Convolution2D(256, 3, 3, activation='relu'))
model.add(pooling_func())

model.add(ZeroPadding2D((1, 1)))
model.add(Convolution2D(512, 3, 3, activation='relu', name='conv4_1'))
model.add(ZeroPadding2D((1, 1)))
model.add(Convolution2D(512, 3, 3, activation='relu', name='conv4_2'))
model.add(ZeroPadding2D((1, 1)))
model.add(Convolution2D(512, 3, 3, activation='relu'))
model.add(pooling_func())

model.add(ZeroPadding2D((1, 1)))
model.add(Convolution2D(512, 3, 3, activation='relu', name='conv5_1'))
model.add(ZeroPadding2D((1, 1)))
model.add(Convolution2D(512, 3, 3, activation='relu', name='conv5_2'))
model.add(ZeroPadding2D((1, 1)))
model.add(Convolution2D(512, 3, 3, activation='relu'))
model.add(pooling_func())

# load the weights of the VGG16 networks
# (trained on ImageNet, won the ILSVRC competition in 2014)
# note: when there is a complete match between your model definition
# and your weight savefile, you can simply call model.load_weights(filename)
assert os.path.exists(weights_path), 'Model weights not found (see "weights_path" variable in script).'
f = h5py.File(weights_path)
for k in range(f.attrs['nb_layers']):
    if k >= len(model.layers):
        # we don't look at the last (fully-connected) layers in the savefile
        break
    g = f['layer_{}'.format(k)]
    weights = [g['param_{}'.format(p)] for p in range(g.attrs['nb_params'])]
    model.layers[k].set_weights(weights)
f.close()
print('Model loaded.')

# get the symbolic outputs of each "key" layer (we gave them unique names).
outputs_dict = dict([(layer.name, layer.output) for layer in model.layers])

# resolve_expression the neural style loss
# first we need to define 4 util functions

# the gram matrix of an image tensor (feature-wise outer product)
def gram_matrix(x):
    assert K.ndim(x) == 3
    features = K.batch_flatten(x)
    gram = K.dot(features, K.transpose(features))
    return gram

# the "style loss" is designed to maintain
# the style of the reference image in the generated image.
# It is based on the gram matrices (which capture style) of
# feature maps from the style reference image
# and from the generated image
def style_loss(style, combination):
    assert K.ndim(style) == 3
    assert K.ndim(combination) == 3
    S = gram_matrix(style)
    C = gram_matrix(combination)
    channels = 3
    size = img_width * img_height
    return K.sum(K.square(S - C)) / (4. * (channels ** 2) * (size ** 2))

# an auxiliary loss function
# designed to maintain the "content" of the
# base image in the generated image
def content_loss(base, style, combination):
    # Changes from equation 7 (Pg# 5)
    G = style / (base + 1e-04)
    G_clamped = K.max(K.min(G, g_max), g_min) # Clamping values
    Fm = base * G_clamped
    return K.sum(K.square(combination - Fm))

# the 3rd loss function, total variation loss,
# designed to keep the generated image locally coherent
def total_variation_loss(x):
    assert K.ndim(x) == 4
    a = K.square(x[:, :, :img_width-1, :img_height-1] - x[:, :, 1:, :img_height-1])
    b = K.square(x[:, :, :img_width-1, :img_height-1] - x[:, :, :img_width-1, 1:])
    return K.sum(K.pow(a + b, 1.25))

# combine these loss functions into a single scalar
loss = K.variable(0.)
feature_layers = ['conv3_1', 'conv4_1'] # Only conv3_1 and conv4_1 used in paper (Pg# 5)

content_weight = style_weight = 0.5 # Alpha and Beta (content and style weights) are 0.5, Pg# 5

# Calculating content loss
for layer_name in feature_layers:
    layer_features = outputs_dict[layer_name] # 'conv3_1' or 'conv4_1'
    base_image_features = layer_features[0, :, :, :]
    style_features = layer_features[1, :, :, :]
    combination_features = layer_features[2, :, :, :]
    loss += content_weight * content_loss(base_image_features, style_features, combination_features)

# Calculating style loss (in this case, painting style loss)
temp_loss = K.variable(0.0)

for layer_name in feature_layers:
    layer_features = outputs_dict[layer_name]
    style_reference_features = layer_features[1, :, :, :]
    combination_features = layer_features[2, :, :, :]
    sl = style_loss(style_reference_features, combination_features)
    temp_loss += (style_weight / len(feature_layers)) * sl

gamma = 100 # Gamma weight defined as 100 in Pg# 5
loss += temp_loss * gamma

loss += total_variation_weight * total_variation_loss(combination_image)

# get the gradients of the generated image wrt the loss
grads = K.gradients(loss, combination_image)

outputs = [loss]
if type(grads) in {list, tuple}:
    outputs += grads
else:
    outputs.append(grads)

f_outputs = K.function([combination_image], outputs)
def eval_loss_and_grads(x):
    x = x.reshape((1, 3, img_width, img_height))
    outs = f_outputs([x])
    loss_value = outs[0]
    if len(outs[1:]) == 1:
        grad_values = outs[1].flatten().astype('float64')
    else:
        grad_values = np.array(outs[1:]).flatten().astype('float64')
    return loss_value, grad_values

# this Evaluator class makes it possible
# to resolve_expression loss and gradients in one pass
# while retrieving them via two separate functions,
# "loss" and "grads". This is done because scipy.optimize
# requires separate functions for loss and gradients,
# but computing them separately would be inefficient.
class Evaluator(object):
    def __init__(self):
        self.loss_value = None
        self.grads_values = None

    def loss(self, x):
        assert self.loss_value is None
        loss_value, grad_values = eval_loss_and_grads(x)
        self.loss_value = loss_value
        self.grad_values = grad_values
        return self.loss_value

    def grads(self, x):
        assert self.loss_value is not None
        grad_values = np.copy(self.grad_values)
        self.loss_value = None
        self.grad_values = None
        return grad_values

evaluator = Evaluator()

# run scipy-based optimization (L-BFGS) over the pixels of the generated image
# so as to minimize the neural style loss

assert args.init_image in ["content", "noise"] , "init_image must be one of ['content', 'noise']"
if "content" in args.init_image:
    x = preprocess_image(base_image_path, True)
else:
    x = np.random.uniform(0, 255, (1, 3, img_width, img_height))
    x[0, 0, :, :] -= 103.939
    x[0, 1, :, :] -= 116.779
    x[0, 2, :, :] -= 123.68

num_iter = args.num_iter
for i in range(num_iter):
    print('Start of iteration', (i+1))
    start_time = time.time()

    x, min_val, info = fmin_l_bfgs_b(evaluator.loss, x.flatten(),
                                     fprime=evaluator.grads, maxfun=20)
    print('Current loss value:', min_val)
    # save current generated image
    img = deprocess_image(x.copy().reshape((3, img_width, img_height)))

    if (maintain_aspect_ratio) & (not rescale_image):
        img_ht = int(img_width * aspect_ratio)
        print("Rescaling Image to (%d, %d)" % (img_width, img_ht))
        img = imresize(img, (img_width, img_ht), interp=args.rescale_method)

    if rescale_image:
        print("Rescaling Image to (%d, %d)" % (img_WIDTH, img_HEIGHT))
        img = imresize(img, (img_WIDTH, img_HEIGHT), interp=args.rescale_method)

    fname = result_prefix + '_at_iteration_%d.png' % (i+1)
    imsave(fname, img)
    end_time = time.time()
    print('Image saved as', fname)
    print('Iteration %d completed in %ds' % (i+1, end_time - start_time))