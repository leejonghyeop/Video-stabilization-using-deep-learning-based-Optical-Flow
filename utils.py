import tensorflow as tf
import tensorlayer as tl
from tensorlayer.prepro import *
from config import config, log_config
from skimage import feature
from skimage import color
from scipy.ndimage.filters import gaussian_filter

import scipy
import numpy as np
import cv2
import math

import os
import fnmatch

def read_all_imgs(file_name_list, path = '', mode = 'RGB'):
    imgs = []
    for idx in range(0, len(file_name_list)):
        imgs.append(get_images(file_name_list[idx], path, mode))
        
    return imgs 

def get_images(file_name, path, mode):
    """ Input an image path and name, return an image array """
    # return scipy.misc.imread(path + file_name).astype(np.float)
    if mode is 'RGB':
        image = scipy.misc.imread(path + file_name, mode='RGB')/255.
    elif mode is 'GRAY':
        image = scipy.misc.imread(path + file_name, mode='P')/255.
        image = np.expand_dims(1 - image, axis = 2)
    elif mode is 'DEPTH':
        image = (np.float32(cv2.imread(path + file_name, cv2.IMREAD_UNCHANGED))/10.)[:, :, 1]
        image[np.where(image < 1)] = 1
        image = (image - 1) / 2. # 7
        image = 1 - image / 7.
        image = np.expand_dims(image, axis = 2)

    return image

def t_or_f(arg):
    ua = str(arg).upper()
    if 'TRUE'.startswith(ua):
       return True
    elif 'FALSE'.startswith(ua):
       return False
    else:
       pass 

def activation_map(gray):
    red = np.expand_dims(np.ones_like(gray), axis = 2)
    green = np.expand_dims(np.ones_like(gray), axis = 2)
    blue = np.expand_dims(np.ones_like(gray), axis = 2)
    gray = np.expand_dims(gray, axis = 2)

    red[(gray == 0.)] = 0.
    green[(gray == 0.)] = 0.
    blue[(gray == 0.)] = 0.

    red[(gray <= 1./3)&(gray > 0.)] = 1.
    green[(gray <= 1./3)&(gray > 0.)] = 3. * gray[(gray <= 1./3.)&(gray > 0.)]
    blue[(gray <= 1./3)&(gray > 0.)] = 0.

    red[(gray > 1./3)&(gray <= 2./3)] = -3. * (gray[(gray > 1./3)&(gray <= 2./3)] - 1./3.) + 1.
    green[(gray > 1./3)&(gray <= 2./3)] = 1.
    blue[(gray > 1./3)&(gray <= 2./3)] = 0.

    red[(gray > 2./3)] = 0.
    green[(gray > 2./3)] = -3. * (gray[(gray > 2./3)] - 2./3.) + 1.
    blue[(gray > 2./3)] = 3. * (gray[(gray > 2./3)] - 2./3.)

    return np.concatenate((red, green, blue), axis = 2) * 255.

def _tf_fspecial_gauss(size, sigma):
    """Function to mimic the 'fspecial' gaussian MATLAB function
    """
    x_data, y_data = np.mgrid[-size//2 + 1:size//2 + 1, -size//2 + 1:size//2 + 1]

    x_data = np.expand_dims(x_data, axis=-1)
    x_data = np.expand_dims(x_data, axis=-1)

    y_data = np.expand_dims(y_data, axis=-1)
    y_data = np.expand_dims(y_data, axis=-1)

    x = tf.constant(x_data, dtype=tf.float32)
    y = tf.constant(y_data, dtype=tf.float32)

    g = tf.exp(-((x**2 + y**2)/(2.0*sigma**2)))
    return g / tf.reduce_sum(g)

def tf_ssim(img1, img2, mean_metric = True, cs_map=False, size=9, sigma=0.5):
    window = _tf_fspecial_gauss(size, sigma) # window shape [size, size]
    K1 = 0.01
    K2 = 0.03
    L = 1  # depth of image (255 in case the image has a differnt scale)
    C1 = (K1*L)**2
    C2 = (K2*L)**2
    C3 = C2/2.
    mu1 = tf.nn.conv2d(img1, window, strides=[1,1,1,1], padding='VALID')
    mu2 = tf.nn.conv2d(img2, window, strides=[1,1,1,1],padding='VALID')
    mu1_sq = mu1*mu1
    mu2_sq = mu2*mu2
    mu1_mu2 = mu1*mu2
    sigma1_sq = tf.nn.conv2d(img1*img1, window, strides=[1,1,1,1],padding='VALID') - mu1_sq
    sigma2_sq = tf.nn.conv2d(img2*img2, window, strides=[1,1,1,1],padding='VALID') - mu2_sq
    sigma12 = tf.nn.conv2d(img1*img2, window, strides=[1,1,1,1],padding='VALID') - mu1_mu2

    l = (2 * mu1 * mu2 + C1)/(mu1_sq + mu2_sq + C1)
    c = (2 * tf.sqrt(sigma1_sq) * tf.sqrt(sigma2_sq) + C2) / (sigma1_sq + sigma2_sq + C2)
    #s = (sigma12 + C3)/(tf.sqrt(sigma1_sq) * tf.sqrt(sigma2_sq) + C3)
    s = (sigma12**2 + C3)/(sigma1_sq * sigma2_sq + C3)
    if cs_map:
        value = ( l ** 0, (c ** 0) * s)
    else:
        '''
        value = ((2*mu1_mu2 + C1)*(2*sigma12 + C2))/((mu1_sq + mu2_sq + C1)*
                    (sigma1_sq + sigma2_sq + C2))
        '''
        value = s

    if mean_metric:
        value = tf.reduce_mean(value)

    return value

def tf_ms_ssim(img1, img2, batch_size, mean_metric=True, level=5):
    #weight = [0.0448, 0.2856, 0.3001, 0.2363, 0.1333]
    weight = [1., 1., 1., 1., 1.]

    ml = []
    mcs = []
    image1 = img1
    image2 = img2
    for l in range(level):
        l_map, cs_map = tf_ssim(image1, image2, cs_map=True, mean_metric=False)

        l_map_mean = tf.reduce_mean(tf.reshape(l_map, [batch_size, -1]), axis=1)
        cs_map_mean = tf.reduce_mean(tf.reshape(cs_map, [batch_size, -1]), axis=1)

        #l_map_mean = tf.Print(l_map_mean, [l_map_mean], message = 'l_map_{}'.format(l), summarize = 10)
        #cs_map_mean = tf.Print(cs_map_mean, [cs_map_mean], message = 'cs_map_{}'.format(l), summarize = 10)

        ml.append(l_map_mean)
        mcs.append(cs_map_mean)

        image1 = tf.nn.avg_pool(image1, [1,2,2,1], [1,2,2,1], padding='SAME')
        image2 = tf.nn.avg_pool(image2, [1,2,2,1], [1,2,2,1], padding='SAME')

    # list to tensor of dim D+1
    ml = tf.stack(ml, axis=0)
    mcs = tf.stack(mcs, axis=0)

    mat = np.copy(weight)
    for i in np.arange(batch_size - 1):
        mat = np.concatenate((mat, weight))
    mat = np.reshape(mat, [batch_size, level])
    mat = np.transpose(mat)

    weight_mat = tf.constant(mat, shape=[level, batch_size], dtype=tf.float32)
    #weight_mat = tf.Print(weight_mat, [weight_mat], message = 'w_mat', summarize = 50)

    value = (ml[level-1]**tf.constant(weight[level-1], shape=[batch_size])) * tf.reduce_prod(mcs[0:level]**weight_mat)

    if mean_metric:
        value = tf.reduce_mean(value)
    return value

def refine_image(img):
    h, w = img.shape[:2]
    
    return img[0 : h - h % 16, 0 : w - w % 16]

def random_crop(images, resize_shape, max_size_limit = 800, is_random_flip = False, is_gaussian_noise = False):
    images_list = None
    h, w = resize_shape[:2]
    
    for i in np.arange(len(images)):
        image = np.copy(images[i])
        shape = np.array(image.shape[:2])
        
        if shape.min() <= h:
            ratio = resize_shape[shape.argmin()]/float(shape.min())
            resize_w = int(math.floor(shape[1] * ratio)) + 1
            resize_h = int(math.floor(shape[0] * ratio)) + 1
            image = cv2.resize(image, (resize_w, resize_h))

        if shape.min() > max_size_limit:
            ratio = max_size_limit/float(shape.min())
            resize_w = int(math.floor(shape[1] * ratio)) + 1
            resize_h = int(math.floor(shape[0] * ratio)) + 1
            image = cv2.resize(image, (resize_w, resize_h))

        if is_gaussian_noise:
            image = add_gaussian_noise(image)

        augmented_image = tl.prepro.crop(image, wrg=w, hrg=h, is_random=True)
        if is_random_flip:
            augmented_image = random_flip(cropped_image)
            angles = np.array([1, 2, 3, 4])
            angle = np.random.choice(angles)
            augmented_image = random_rotation(augmented_image, angle)

        image = np.expand_dims(augmented_image, axis=0)
        
        images_list = np.copy(image) if i == 0 else np.concatenate((images_list, image), axis = 0)

    return images_list

def crop_pair_with_different_shape_images_2(images, labels, resize_shape, is_gaussian_noise = False):
    images_list = None
    labels_list = None
    h, w = resize_shape[:2]
    max_size_limit = 800
    
    for i in np.arange(len(images)):
        image = np.copy(images[i])
        label = np.copy(labels[i])
        shape = np.array(image.shape[:2])
        
        if shape.min() <= h:
            ratio = resize_shape[shape.argmin()]/float(shape.min())
            resize_w = int(math.floor(shape[1] * ratio)) + 1
            resize_h = int(math.floor(shape[0] * ratio)) + 1
            image = cv2.resize(image, (resize_w, resize_h))
            label = np.expand_dims(cv2.resize(label[:, :, 0], (resize_w, resize_h)), axis = 2)

        if shape.min() > max_size_limit:
            ratio = max_size_limit/float(shape.min())
            resize_w = int(math.floor(shape[1] * ratio)) + 1
            resize_h = int(math.floor(shape[0] * ratio)) + 1
            image = cv2.resize(image, (resize_w, resize_h))
            label = np.expand_dims(cv2.resize(label[:, :, 0], (resize_w, resize_h)), axis = 2)

        if is_gaussian_noise:
            image = add_gaussian_noise(image)

        concatenated_images = np.concatenate((image, label), axis = 2)
        cropped_images = tl.prepro.crop(concatenated_images, wrg=w, hrg=h, is_random=True)
        augmented_images = random_flip(cropped_images)
        angles = np.array([1, 2, 3, 4])
        angle = np.random.choice(angles)
        augmented_images = random_rotation(augmented_images, angle)

        image = np.expand_dims(augmented_images[:, :, 0:3], axis=0)
        label = np.expand_dims(np.expand_dims(augmented_images[:, :, 3], axis=3), axis=0)
        
        images_list = np.copy(image) if i == 0 else np.concatenate((images_list, image), axis = 0)
        labels_list = np.copy(label) if i == 0 else np.concatenate((labels_list, label), axis = 0)

    return images_list, labels_list

def crop_pair_with_different_shape_images_3(images, labels, labels2, resize_shape, is_gaussian_noise = False):
    images_list = None
    labels_list = None
    labels2_list = None
    h, w = resize_shape[:2]
    max_size_limit = 800
    
    for i in np.arange(len(images)):
        image = np.copy(images[i])
        label = np.copy(labels[i])
        label2 = np.copy(labels2[i])
        shape = np.array(image.shape[:2])
        
        if shape.min() <= h:
            ratio = resize_shape[shape.argmin()]/float(shape.min())
            resize_w = int(math.floor(shape[1] * ratio)) + 1
            resize_h = int(math.floor(shape[0] * ratio)) + 1
            image = cv2.resize(image, (resize_w, resize_h))
            label = np.expand_dims(cv2.resize(label[:, :, 0], (resize_w, resize_h)), axis = 2)
            label2 = np.expand_dims(cv2.resize(label2[:, :, 0], (resize_w, resize_h)), axis = 2)

        if shape.min() > max_size_limit:
            ratio = max_size_limit/float(shape.min())
            resize_w = int(math.floor(shape[1] * ratio)) + 1
            resize_h = int(math.floor(shape[0] * ratio)) + 1
            image = cv2.resize(image, (resize_w, resize_h))
            label = np.expand_dims(cv2.resize(label[:, :, 0], (resize_w, resize_h)), axis = 2)
            label2 = np.expand_dims(cv2.resize(label2[:, :, 0], (resize_w, resize_h)), axis = 2)

        if is_gaussian_noise:
            image = add_gaussian_noise(image)

        concatenated_images = np.concatenate((image, label, label2), axis = 2)
        cropped_images = tl.prepro.crop(concatenated_images, wrg=w, hrg=h, is_random=True)
        augmented_images = random_flip(cropped_images)
        angles = np.array([1, 2, 3, 4])
        angle = np.random.choice(angles)
        augmented_images = random_rotation(augmented_images, angle)
        image = np.expand_dims(augmented_images[:, :, :3], axis=0)
        label = np.expand_dims(np.expand_dims(augmented_images[:, :, 3], axis=3), axis=0)
        label2 = np.expand_dims(np.expand_dims(augmented_images[:, :, 4], axis=3), axis=0)
        
        images_list = np.copy(image) if i == 0 else np.concatenate((images_list, image), axis = 0)
        labels_list = np.copy(label) if i == 0 else np.concatenate((labels_list, label), axis = 0)
        labels2_list = np.copy(label2) if i == 0 else np.concatenate((labels2_list, label2), axis = 0)

    return images_list, labels_list, labels2_list

def crop_pair_with_different_shape_images_4(images, labels, labels2, labels3, resize_shape, is_gaussian_noise = False):
    images_list = None
    labels_list = None
    labels2_list = None
    labels3_list = None
    h, w = resize_shape[:2]
    max_size_limit = 800
    
    for i in np.arange(len(images)):
        image = np.copy(images[i])
        label = np.copy(labels[i])
        label2 = np.copy(labels2[i])
        label3 = np.copy(labels3[i])
        shape = np.array(image.shape[:2])
        
        if shape.min() <= h:
            ratio = resize_shape[shape.argmin()]/float(shape.min())
            resize_w = int(math.floor(shape[1] * ratio)) + 1
            resize_h = int(math.floor(shape[0] * ratio)) + 1
            image = cv2.resize(image, (resize_w, resize_h))
            label = np.expand_dims(cv2.resize(label[:, :, 0], (resize_w, resize_h)), axis = 2)
            label2 = np.expand_dims(cv2.resize(label2[:, :, 0], (resize_w, resize_h)), axis = 2)
            label3 = np.expand_dims(cv2.resize(label3[:, :, 0], (resize_w, resize_h)), axis = 2)
            
        if shape.min() > max_size_limit:
            ratio = max_size_limit/float(shape.min())
            resize_w = int(math.floor(shape[1] * ratio)) + 1
            resize_h = int(math.floor(shape[0] * ratio)) + 1
            image = cv2.resize(image, (resize_w, resize_h))
            label = np.expand_dims(cv2.resize(label[:, :, 0], (resize_w, resize_h)), axis = 2)
            label2 = np.expand_dims(cv2.resize(label2[:, :, 0], (resize_w, resize_h)), axis = 2)
            label3 = np.expand_dims(cv2.resize(label3[:, :, 0], (resize_w, resize_h)), axis = 2)
                
        if is_gaussian_noise:
            image = add_gaussian_noise(image)

        concatenated_images = np.concatenate((image, label, label2, label3), axis = 2)
        cropped_images = tl.prepro.crop(concatenated_images, wrg=w, hrg=h, is_random=True)

        augmented_images = random_flip(cropped_images)
        angles = np.array([1, 2, 3, 4])
        angle = np.random.choice(angles)
        augmented_images = random_rotation(augmented_images, angle)
        image = np.expand_dims(augmented_images[:, :, :3], axis=0)
        label = np.expand_dims(np.expand_dims(augmented_images[:, :, 3], axis=3), axis=0)
        label2 = np.expand_dims(np.expand_dims(augmented_images[:, :, 4], axis=3), axis=0)
        label3 = np.expand_dims(np.expand_dims(augmented_images[:, :, 5], axis=3), axis=0)
        
        images_list = np.copy(image) if i == 0 else np.concatenate((images_list, image), axis = 0)
        labels_list = np.copy(label) if i == 0 else np.concatenate((labels_list, label), axis = 0)
        labels2_list = np.copy(label2) if i == 0 else np.concatenate((labels2_list, label2), axis = 0)
        labels3_list = np.copy(label3) if i == 0 else np.concatenate((labels3_list, label3), axis = 0)

    return images_list, labels_list, labels2_list, labels3_list
def add_gaussian_noise(image):
    # noise_sigma = 0.01
    # h = image.shape[0]
    # w = image.shape[1]
    # noise = np.random.randn(h, w) * noise_sigma

    # noisy_image = np.zeros(image.shape, np.float64)
    # if len(image.shape) == 2:
    #     noisy_image = image + noise
    # else:
    #     noisy_image[:,:,0] = image[:,:,0] + noise
    #     noisy_image[:,:,1] = image[:,:,1] + noise
    #     noisy_image[:,:,2] = image[:,:,2] + noise

    # """
    # print('min,max = ', np.min(noisy_image), np.max(noisy_image))
    # print('type = ', type(noisy_image[0][0][0]))
    # """

    # return noisy_image
    return image

def random_flip(images):
    flipped_images = tl.prepro.flip_axis(images, axis=0, is_random=True)

    return flipped_images

def random_rotation(images, angle):
    if angle != 4:
        rotated_images = np.rot90(images, angle)
    else:
        rotated_images = images

    return rotated_images

def get_binary_maps(maps):
    continuous_maps = maps
    for i in np.arange(len(continuous_maps)):
        continuous_map = continuous_maps[i]
        continuous_map[np.where(continuous_map > continuous_map.min())] = 1
        continuous_map[np.where(continuous_map == continuous_map.min())] = 0
        continuous_maps[i] = continuous_map

    return continuous_maps
    
def get_file_path(path, regex):
    file_path = []
    for root, dirnames, filenames in os.walk(path):
        for i in np.arange(len(regex)):
            for filename in fnmatch.filter(filenames, regex[i]):
                file_path.append(os.path.join(root, filename))
    
    return file_path

def remove_file_end_with(path, regex):
    file_paths = get_file_path(path, [regex])

    for i in np.arange(len(file_paths)):
        os.remove(file_paths[i])

def save_images(images, size, image_path='_temp.png'):
    if len(images.shape) == 3:  # Greyscale [batch, h, w] --> [batch, h, w, 1]
        images = images[:, :, :, np.newaxis]

    def merge(images, size):
        h, w = images.shape[1], images.shape[2]
        img = np.zeros((h * size[0], w * size[1], 3))
        for idx, image in enumerate(images):
            i = idx % size[1]
            j = idx // size[1]
            img[j * h:j * h + h, i * w:i * w + w, :] = image
        return img

    def imsave(images, size, path):
        return scipy.misc.toimage(merge(images, size), cmin = 0., cmax = 1.).save(path)

    assert len(images) <= size[0] * size[1], "number of images should be equal or less than size[0] * size[1] {}".format(len(images))

    return imsave(images, size, image_path)

def fix_image_tf(image, norm_value):
    return tf.cast(image / norm_value * 255., tf.uint8)

def norm_image_tf(image):
    image = image - tf.reduce_min(image, axis = [1, 2, 3], keepdims=True)
    image = image / tf.reduce_max(image, axis = [1, 2, 3], keepdims=True)
    return tf.cast(image * 255., tf.uint8)

def norm_image(image, axis = (1, 2, 3)):
    image = image - np.amin(image, axis = axis, keepdims=True)
    image = image / np.amax(image, axis = axis, keepdims=True)
    return image
        
def entry_stop_gradients(target, mask):
    mask_h = tf.abs(mask-1)
    return tf.stop_gradient(mask_h * target) + mask * target

def get_disc_accuracy(logits, labels):
    acc = 0.
    for i in np.arange(len(logits)):
        tp = 0
        logits[i] = np.round(np.squeeze(logits[i])).astype(int)
        temp = logits[i]
        tp = tp + len(temp[np.where(temp == labels[i])])
        acc = acc + (tp / float(len(logits[i])))
    return acc / float(len(labels))

def get_frame_batch(frames, cap, sample_num, batch_size, n_frames, resize_shape, upper_limit_to_resize):
    is_end = False
    w, h = resize_shape
    max_size_limit = upper_limit_to_resize

    if n_frames == 0:
        frames = []
        itr_num = (sample_num - 1) + batch_size
    else:
        itr_num = batch_size

    for i in np.arange(itr_num):
        if n_frames != 0:
            del(frames[0]) 
        ref, frame = cap.read()
        if ref == False:
            is_end = True
            break

        shape = np.array(frame.shape[:2])
        if shape.min() <= h:
            ratio = resize_shape[shape.argmin()]/float(shape.min())
            resize_w = int(math.floor(shape[1] * ratio)) + 1
            resize_h = int(math.floor(shape[0] * ratio)) + 1
            frame = cv2.resize(frame, (resize_w, resize_h))

        if shape.min() > upper_limit_to_resize:
            ratio = upper_limit_to_resize/float(shape.min())
            resize_w = int(math.floor(shape[1] * ratio)) + 1
            resize_h = int(math.floor(shape[0] * ratio)) + 1
            frame = cv2.resize(frame, (resize_w, resize_h))

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame = np.expand_dims(frame/255., axis = 0)
        frames.append(frame)

    train_frames = []
    for i in range(0, len(frames) - (sample_num - 1)):
        train_frames_temp = np.concatenate(frames[i:i+sample_num], axis = 0)
        train_frames_temp = np.expand_dims(train_frames_temp, axis = 0)
        if i == 0:
            train_frames = train_frames_temp
        else:
            train_frames = np.concatenate((train_frames, train_frames_temp), axis = 0)

    return frames, train_frames, is_end

def crop_frames(frames_1, frames_2, crop_size, batch_size, sample_num):
    w, h = crop_size
    shape = frames_1.shape
    frames_1 = np.reshape(frames_1, [batch_size * sample_num, shape[2], shape[3], 3])
    frames_2 = np.reshape(frames_2, [batch_size * sample_num, shape[2], shape[3], 3])
    frames_concat = np.concatenate((frames_1, frames_2), axis = 0)
    #print(w)
    #print(h)
    #print(frames_concat.shape)
    max_size_limit = 800
    
    for i in range(batch_size * sample_num * 2):
        curimage = np.copy(frames_concat[i])
        curshape = np.array(curimage.shape[:2])
        resize_shape = [w,h]
        resize_h = curshape[0]
        resize_w = curshape[1]
        
        if curshape.min() <= h:
            ratio = resize_shape[curshape.argmin()]/float(curshape.min())
            resize_w = int(math.floor(curshape[1] * ratio)) + 1
            resize_h = int(math.floor(curshape[0] * ratio)) + 1

        if curshape.min() > max_size_limit:
            ratio = max_size_limit/float(curshape.min())
            resize_w = int(math.floor(curshape[1] * ratio)) + 1
            resize_h = int(math.floor(curshape[0] * ratio)) + 1

        curimage = cv2.resize(curimage, (resize_w, resize_h))
        if i == 0:
            frames_concat_resize = np.zeros((2 * batch_size * sample_num,  resize_h, resize_w, 3) )
            #print(frames_concat_resize.shape)
        frames_concat_resize[i] = curimage

    frames_concat_cropped = tl.prepro.crop_multi(frames_concat_resize, w, h, is_random=True)
    #print(frames_concat_cropped.shape)

    frames_1 = frames_concat_cropped[:batch_size * sample_num]
    frames_2 = frames_concat_cropped[batch_size * sample_num:]

    frames_1 = np.reshape(frames_1, [batch_size, sample_num, w, h, 3])
    frames_2 = np.reshape(frames_2, [batch_size, sample_num, w, h, 3])

    return frames_1, frames_2

def resize_frames(frames_1, frames_2, crop_size, batch_size, sample_num):
    w, h = crop_size
    shape = frames_1.shape
    frames_1 = np.reshape(frames_1, [batch_size * sample_num, shape[2], shape[3], 3])
    frames_2 = np.reshape(frames_2, [batch_size * sample_num, shape[2], shape[3], 3])
    frames_concat = np.concatenate((frames_1, frames_2), axis = 0)
    #print(w)
    #print(h)
    #print(frames_concat.shape)
    max_size_limit = 800
    
    for i in range(batch_size * sample_num * 2):
        curimage = np.copy(frames_concat[i])
        curimage = cv2.resize(curimage, (w, h))
        if i == 0:
            frames_concat_resize = np.zeros((2 * batch_size * sample_num,  h, w, 3) )
            #print(frames_concat_resize.shape)
        frames_concat_resize[i] = curimage

    frames_1 = frames_concat_resize[:batch_size * sample_num]
    frames_2 = frames_concat_resize[batch_size * sample_num:]

    frames_1 = np.reshape(frames_1, [batch_size, sample_num, w, h, 3])
    frames_2 = np.reshape(frames_2, [batch_size, sample_num, w, h, 3])

    return frames_1, frames_2

def resize_frames_single(frames_1, crop_size, batch_size, sample_num):
    w, h = crop_size
    shape = frames_1.shape
    frames_1 = np.reshape(frames_1, [batch_size * sample_num, shape[2], shape[3], 3])
    #print(w)
    #print(h)
    #print(frames_concat.shape)
    max_size_limit = 800
    
    for i in range(batch_size * sample_num):
        curimage = np.copy(frames_1[i])
        curimage = cv2.resize(curimage, (w, h))
        if i == 0:
            frames_concat_resize = np.zeros((2 * batch_size * sample_num,  h, w, 3) )
            #print(frames_concat_resize.shape)
        frames_concat_resize[i] = curimage

    frames_1 = frames_concat_resize[:batch_size * sample_num]

    frames_1 = np.reshape(frames_1, [batch_size, sample_num, w, h, 3])

    return frames_1

def tf_diff(a):
    return a[:, 1:, :, :, :] - a[:, :-1, :, :, :]
