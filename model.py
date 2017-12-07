import tensorflow as tf
import numpy as np
import math
from PIL import Image
from matplotlib import pyplot as plt
from image_data_loader import ImageData, ImageAndPriorData
import os
import time

def get_conv_weights(weight_shape, sess):
    return math.sqrt(2 / (9.0 * 64)) * sess.run(tf.truncated_normal(weight_shape))

def mean_averge_error(pred, target):
    error = abs(np.squeeze(pred) - np.squeeze(target))
    mae = np.sum(error) / error.size
    return mae

class DCL(object):

    def __init__(self, sess, lr=0.000001, ckpt_dir='./parameters'):
        self.sess = sess
        self.ckpt_dir = ckpt_dir
        self.lr = lr
        self.build2()


    def conv2d(self, x, w_shape, name):
        w = tf.Variable(tf.truncated_normal(shape=w_shape), dtype=tf.float32, name=name + '_w')
        b = tf.Variable(tf.truncated_normal(shape=[1, 1, 1, w_shape[-1]]), dtype=tf.float32, name=name + '_b')
        return tf.nn.conv2d(x, w, strides=[1, 1, 1, 1], padding='SAME') + b

    def astro_conv2d(self, x, w_shape, hole=2, name='astro_conv'):
        w = tf.Variable(tf.truncated_normal(shape=w_shape), dtype=tf.float32, name=name + '_w')
        b = tf.Variable(tf.truncated_normal(shape=[1, 1, 1, w_shape[-1]]), dtype=tf.float32, name=name + '_b')
        return tf.nn.atrous_conv2d(x, w, rate=hole, padding='SAME') + b

    def max_pool(x):
        return tf.nn.max_pool(x, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME')

    def build2(self):
        self.X = tf.placeholder(tf.float32, [None, 512, 512, 3], name='rgb_image')
        self.X_prior = tf.placeholder(tf.float32, [None, 512, 512, 4], name='rgb_prior_image')
        self.Y = tf.placeholder(tf.float32, [None, 512, 512, 1], name='gt')

        ############### R1 ###############
        conv1_1 = tf.nn.relu(self.conv2d(self.X, [3, 3, 3, 64], 'conv1_1'))
        conv1_2 = tf.nn.relu(self.conv2d(conv1_1, [3, 3, 64, 64], 'conv1_2'))
        pool1 = tf.nn.max_pool(conv1_2, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME', name='pool1')
        conv2_1 = tf.nn.relu(self.conv2d(pool1, [3, 3, 64, 128], 'conv2_1'))
        conv2_2 = tf.nn.relu(self.conv2d(conv2_1, [3, 3, 128, 128], 'conv2_2'))
        pool2 = tf.nn.max_pool(conv2_2, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME', name='pool2')
        conv3_1 = tf.nn.relu(self.conv2d(pool2, [3, 3, 128, 256], 'conv3_1'))
        conv3_2 = tf.nn.relu(self.conv2d(conv3_1, [3, 3, 256, 256], 'conv3_2'))
        conv3_3 = tf.nn.relu(self.conv2d(conv3_2, [3, 3, 256, 256], 'conv3_3'))
        pool3 = tf.nn.max_pool(conv3_3, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME', name='pool3')
        conv4_1 = tf.nn.relu(self.conv2d(pool3, [3, 3, 256, 512], 'conv4_1'))
        conv4_2 = tf.nn.relu(self.conv2d(conv4_1, [3, 3, 512, 512], 'conv4_2'))
        conv4_3 = tf.nn.relu(self.conv2d(conv4_2, [3, 3, 512, 512], 'conv4_3'))
        pool4 = tf.nn.max_pool(conv4_3, ksize=[1, 3, 3, 1], strides=[1, 1, 1, 1], padding='SAME', name='pool4')

        conv5_1 = tf.nn.relu(self.astro_conv2d(pool4, [3, 3, 512, 512], hole=2, name='conv5_1'))
        conv5_2 = tf.nn.relu(self.astro_conv2d(conv5_1, [3, 3, 512, 512], hole=2, name='conv5_2'))
        conv5_3 = tf.nn.relu(self.astro_conv2d(conv5_2, [3, 3, 512, 512], hole=2, name='conv5_3'))
        pool5 = tf.nn.max_pool(conv5_3, ksize=[1, 3, 3, 1], strides=[1, 1, 1, 1], padding='SAME')

        fc6 = tf.nn.relu(self.astro_conv2d(pool5, [4, 4, 512, 4096], hole=4, name='fc6'))
        fc6_dropout = tf.nn.dropout(fc6, 0.5)

        fc7 = tf.nn.relu(self.astro_conv2d(fc6_dropout, [1, 1, 4096, 4096], hole=4, name='fc7'))
        fc7_dropout = tf.nn.dropout(fc7, 0.5)

        fc8 = self.conv2d(fc7_dropout, [1, 1, 4096, 1], 'fc8')
        up_fc8 = tf.image.resize_bilinear(fc8, [512, 512])

        pool4_conv = tf.nn.dropout(tf.nn.relu(self.conv2d(pool4, [3, 3, 512, 128], 'pool4_conv')), 0.5)
        pool4_fc = tf.nn.dropout(tf.nn.relu(self.conv2d(pool4_conv, [1, 1, 128, 128], 'pool4_fc')), 0.5)
        pool4_ms_saliency = self.conv2d(pool4_fc, [1, 1, 128, 1], 'pool4_ms_saliency')
        up_pool4 = tf.image.resize_bilinear(pool4_ms_saliency, [512, 512])
        final_saliency_r1 = tf.add(up_pool4, up_fc8)

        ############### R2 ###############
        conv1_1_r2 = tf.nn.relu(self.conv2d(self.X_prior, [3, 3, 4, 64], 'conv1_1_r2'))
        conv1_2_r2 = tf.nn.relu(self.conv2d(conv1_1_r2, [3, 3, 64, 64], 'conv1_2_r2'))
        pool1_r2 = tf.nn.max_pool(conv1_2_r2, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME', name='pool1_r2')
        conv2_1_r2 = tf.nn.relu(self.conv2d(pool1_r2, [3, 3, 64, 128], 'conv2_1_r2'))
        conv2_2_r2 = tf.nn.relu(self.conv2d(conv2_1_r2, [3, 3, 128, 128], 'conv2_2_r2'))
        pool2_r2 = tf.nn.max_pool(conv2_2_r2, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME', name='pool2_r2')
        conv3_1_r2 = tf.nn.relu(self.conv2d(pool2_r2, [3, 3, 128, 256], 'conv3_1_r2'))
        conv3_2_r2 = tf.nn.relu(self.conv2d(conv3_1_r2, [3, 3, 256, 256], 'conv3_2_r2'))
        conv3_3_r2 = tf.nn.relu(self.conv2d(conv3_2_r2, [3, 3, 256, 256], 'conv3_3_r2'))
        pool3_r2 = tf.nn.max_pool(conv3_3_r2, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME', name='pool3_r2')
        conv4_1_r2 = tf.nn.relu(self.conv2d(pool3_r2, [3, 3, 256, 512], 'conv4_1_r2'))
        conv4_2_r2 = tf.nn.relu(self.conv2d(conv4_1_r2, [3, 3, 512, 512], 'conv4_2_r2'))
        conv4_3_r2 = tf.nn.relu(self.conv2d(conv4_2_r2, [3, 3, 512, 512], 'conv4_3_r2'))
        pool4_r2 = tf.nn.max_pool(conv4_3_r2, ksize=[1, 3, 3, 1], strides=[1, 1, 1, 1], padding='SAME', name='pool4_r2')

        conv5_1_r2 = tf.nn.relu(self.astro_conv2d(pool4_r2, [3, 3, 512, 512], hole=2, name='conv5_1_r2'))
        conv5_2_r2 = tf.nn.relu(self.astro_conv2d(conv5_1_r2, [3, 3, 512, 512], hole=2, name='conv5_2_r2'))
        conv5_3_r2 = tf.nn.relu(self.astro_conv2d(conv5_2_r2, [3, 3, 512, 512], hole=2, name='conv5_3_r2'))
        pool5_r2 = tf.nn.max_pool(conv5_3_r2, ksize=[1, 3, 3, 1], strides=[1, 1, 1, 1], padding='SAME')

        fc6_r2 = tf.nn.relu(self.astro_conv2d(pool5_r2, [4, 4, 512, 4096], hole=4, name='fc6_r2'))
        fc6_dropout_r2 = tf.nn.dropout(fc6_r2, 0.5)

        fc7_r2 = tf.nn.relu(self.astro_conv2d(fc6_dropout_r2, [1, 1, 4096, 4096], hole=4, name='fc7_r2'))
        fc7_dropout_r2 = tf.nn.dropout(fc7_r2, 0.5)

        fc8_r2 = self.conv2d(fc7_dropout_r2, [1, 1, 4096, 1], 'fc8_r2')
        up_fc8_r2 = tf.image.resize_bilinear(fc8_r2, [512, 512])

        pool4_conv_r2 = tf.nn.dropout(tf.nn.relu(self.conv2d(pool4_r2, [3, 3, 512, 128], 'pool4_conv_r2')), 0.5)
        pool4_fc_r2 = tf.nn.dropout(tf.nn.relu(self.conv2d(pool4_conv_r2, [1, 1, 128, 128], 'pool4_fc_r2')), 0.5)
        pool4_ms_saliency_r2 = self.conv2d(pool4_fc_r2, [1, 1, 128, 1], 'pool4_ms_saliency_r2')
        up_pool4_r2 = tf.image.resize_bilinear(pool4_ms_saliency_r2, [512, 512])
        final_saliency_r2 = tf.add(up_pool4_r2, up_fc8_r2)

        ########### ST fusion ############
        pool4_saliency_cancat = tf.concat([pool4_ms_saliency, pool4_ms_saliency_r2], 3, name='concat_pool4')
        pool4_saliency_ST = self.conv2d(pool4_saliency_cancat, [1, 1, 2, 1], 'pool4_saliency_ST')
        up_pool4_ST = tf.image.resize_bilinear(pool4_saliency_ST, [512, 512])

        fc8_concat = tf.concat([fc8, fc8_r2], 3, name='concat_fc8')
        fc8_saliency_ST = self.conv2d(fc8_concat, [1, 1, 2, 1], 'fc8_saliency_ST')
        up_fc8_ST = tf.image.resize_bilinear(fc8_saliency_ST, [512, 512])


        final_saliency = tf.add(up_pool4_ST, up_fc8_ST)
        self.final_saliency = tf.sigmoid(final_saliency)
        self.up_fc8 = up_fc8
        self.saver = tf.train.Saver()


        self.loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=final_saliency, labels=self.Y), name='loss')
        tf.summary.scalar('entropy', self.loss)

        optimizer = tf.train.AdamOptimizer(self.lr, name='optimizer')
        trainable_var = tf.trainable_variables()
        grads = optimizer.compute_gradients(self.loss, var_list=trainable_var)
        self.train_op = optimizer.apply_gradients(grads)


    def build(self):
        self.X = tf.placeholder(tf.float32, [None, 512, 512, 3], name='rgb_image')
        self.Y = tf.placeholder(tf.float32, [None, 512, 512, 1], name='gt')

        conv1_1 = tf.nn.relu(self.conv2d(self.X, [3, 3, 3, 64], 'conv1_1'))
        conv1_2 = tf.nn.relu(self.conv2d(conv1_1, [3, 3, 64, 64], 'conv1_2'))
        pool1 = tf.nn.max_pool(conv1_2, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME', name='pool1')
        conv2_1 = tf.nn.relu(self.conv2d(pool1, [3, 3, 64, 128], 'conv2_1'))
        conv2_2 = tf.nn.relu(self.conv2d(conv2_1, [3, 3, 128, 128], 'conv2_2'))
        pool2 = tf.nn.max_pool(conv2_2, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME', name='pool2')
        conv3_1 = tf.nn.relu(self.conv2d(pool2, [3, 3, 128, 256], 'conv3_1'))
        conv3_2 = tf.nn.relu(self.conv2d(conv3_1, [3, 3, 256, 256], 'conv3_2'))
        conv3_3 = tf.nn.relu(self.conv2d(conv3_2, [3, 3, 256, 256], 'conv3_3'))
        pool3 = tf.nn.max_pool(conv3_3, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME', name='pool3')
        conv4_1 = tf.nn.relu(self.conv2d(pool3, [3, 3, 256, 512], 'conv4_1'))
        conv4_2 = tf.nn.relu(self.conv2d(conv4_1, [3, 3, 512, 512], 'conv4_2'))
        conv4_3 = tf.nn.relu(self.conv2d(conv4_2, [3, 3, 512, 512], 'conv4_3'))
        pool4 = tf.nn.max_pool(conv4_3, ksize=[1, 3, 3, 1], strides=[1, 1, 1, 1], padding='SAME', name='pool4')

        conv5_1 = tf.nn.relu(self.astro_conv2d(pool4, [3, 3, 512, 512], hole=2, name='conv5_1'))
        conv5_2 = tf.nn.relu(self.astro_conv2d(conv5_1, [3, 3, 512, 512], hole=2, name='conv5_2'))
        conv5_3 = tf.nn.relu(self.astro_conv2d(conv5_2, [3, 3, 512, 512], hole=2, name='conv5_3'))
        pool5 = tf.nn.max_pool(conv5_3, ksize=[1, 3, 3, 1], strides=[1, 1, 1, 1], padding='SAME')

        fc6 = tf.nn.relu(self.astro_conv2d(pool5, [4, 4, 512, 4096], hole=4, name='fc6'))
        fc6_dropout = tf.nn.dropout(fc6, 0.5)

        fc7 = tf.nn.relu(self.astro_conv2d(fc6_dropout, [1, 1, 4096, 4096], hole=4, name='fc7'))
        fc7_dropout = tf.nn.dropout(fc7, 0.5)

        fc8 = self.conv2d(fc7_dropout, [1, 1, 4096, 1], 'fc8')
        up_fc8 = tf.image.resize_bilinear(fc8, [512, 512])

        pool4_conv = tf.nn.dropout(tf.nn.relu(self.conv2d(pool4, [3, 3, 512, 128], 'pool4_conv')), 0.5)
        pool4_fc = tf.nn.dropout(tf.nn.relu(self.conv2d(pool4_conv, [1, 1, 128, 128], 'pool4_fc')), 0.5)
        pool4_ms_saliency = self.conv2d(pool4_fc, [1, 1, 128, 1], 'pool4_ms_saliency')
        up_pool4 = tf.image.resize_bilinear(pool4_ms_saliency, [512, 512])
        final_saliency = tf.add(up_pool4, up_fc8)
        self.final_saliency = tf.sigmoid(final_saliency)
        self.up_fc8 = up_fc8
        self.saver = tf.train.Saver()


        self.loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=final_saliency, labels=self.Y), name='loss')
        tf.summary.scalar('entropy', self.loss)

        optimizer = tf.train.AdamOptimizer(self.lr, name='optimizer')
        trainable_var = tf.trainable_variables()
        grads = optimizer.compute_gradients(self.loss, var_list=trainable_var)
        self.train_op = optimizer.apply_gradients(grads)



    def train(self):
        image_dir = '/home/ty/data/MSRA5000/images'
        label_dir = '/home/ty/data/MSRA5000/GT2'

        summary_op = tf.summary.merge_all()
        dataset = ImageData(image_dir, label_dir, None, None, '.jpg', '.png', 550, 512, 5, horizontal_flip=True)
        summary_writer = tf.summary.FileWriter('logs', self.sess.graph)
        self.init = tf.global_variables_initializer()

        self.sess.run(self.init)
        self.saver.restore(self.sess, self.ckpt_dir)
        for itr in xrange(10000):
            x, y = dataset.next_batch()
            feed_dict = {self.X: x, self.Y: y}
            self.sess.run(self.train_op, feed_dict=feed_dict)

            if itr % 10 == 0:
                train_loss, saliency, up, summary_str = self.sess.run([self.loss, self.final_saliency, self.up_fc8, summary_op], feed_dict=feed_dict)

                print 'step: %d, train_loss:%g' % (itr, train_loss)
                summary_writer.add_summary(summary_str, itr)

    def train2(self):
        image_dir = '/home/ty/data/davis/480p'
        label_dir = '/home/ty/data/davis/GT'
        prior_dir = '/home/ty/data/davis/davis_flow_prior'
        davis_file = open('/home/ty/data/davis/davis_file.txt')
        image_names = [line.strip() for line in davis_file]

        validate_dir = '/home/ty/data/FBMS/FBMS_Testset2'
        validate_label_dir = '/home/ty/data/FBMS/GT_no_first'
        validate_prior_dir = '/home/ty/data/FBMS/FBMS_Testset_flow_prior'
        FBMS_file = open('/home/ty/data/FBMS/FBMS_file.txt')
        validate_names = [line.strip() for line in FBMS_file]
        # dataset = ImageData(image_dir, label_dir, '.jpg', '.png', 550, 512, 1, horizontal_flip=True)
        dataset = ImageAndPriorData(image_dir, label_dir, prior_dir, validate_dir, validate_label_dir, validate_prior_dir, image_names,
                                    validate_names, '.jpg', '.png', 550, 512, 2, horizontal_flip=False)

        validate_x, validate_y = dataset.get_validate_images()
        summary_op = tf.summary.merge_all()

        summary_writer = tf.summary.FileWriter('logs', self.sess.graph)
        self.init = tf.global_variables_initializer()

        self.sess.run(self.init)
        self.saver.restore(self.sess, self.ckpt_dir)

        save_path = 'tempImages'
        time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())

        for itr in xrange(30000):
            x, y = dataset.next_batch()
            feed_dict = {self.X: x[:, :, :, :3], self.X_prior: x, self.Y: y}
            self.sess.run(self.train_op, feed_dict=feed_dict)

            if itr % 10 == 0:
                train_loss, saliency, up, summary_str = self.sess.run([self.loss, self.final_saliency, self.up_fc8, summary_op],
                                                                      feed_dict=feed_dict)
                print 'step: %d, train_loss:%g' % (itr, train_loss)
                summary_writer.add_summary(summary_str, itr)

            if itr % 100 == 0:
                mae = self.evaluate(validate_x, validate_y)
                print 'during training MAE: ', mae

            if itr % 2000 == 0:

                self.save(str(itr), time_str)

                if not os.path.exists(os.path.join(save_path, time_str)):
                    os.makedirs(os.path.join(save_path, time_str))

                for index in range(validate_x.shape[0]):
                    if index % 30 == 0:
                        test = validate_x[index, :, :, :3]
                        test_prior = validate_x[index, :, :, :]
                        test = test[np.newaxis, ...]
                        test_prior = test_prior[np.newaxis, ...]
                        feed_dict = {self.X: test, self.X_prior: test_prior}
                        saliency = self.sess.run(self.final_saliency, feed_dict=feed_dict)

                        saliency = saliency * 255
                        save_sal = saliency.astype(np.uint8)
                        save_img = Image.fromarray(save_sal[0, :, :, 0])
                        save_img.save(os.path.join(save_path, time_str, str(itr) + '_' + str(index) + '.png'))

    def evaluate(self, x, y):
        mae = 0.0
        for index in range(x.shape[0]):
            test = x[index, :, :, :3]
            test_prior = x[index, :, :, :]
            test = test[np.newaxis, ...]
            test_prior = test_prior[np.newaxis, ...]
            feed_dict = {self.X: test, self.X_prior: test_prior}
            saliency = self.sess.run(self.final_saliency, feed_dict=feed_dict)
            mae += mean_averge_error(saliency, y[index, :, :, :])

        return mae / x.shape[0]

    def save(self, itr, network_name):
        model_dir = os.path.join('models', network_name, itr)
        if not os.path.exists(model_dir):
            os.makedirs(model_dir)

        print 'save model:'
        self.saver.save(self.sess, os.path.join(model_dir, 'snap_model.ckpt'))

    def sampler(self, image):
        self.X_test = tf.placeholder(tf.float32, image.shape, name='test_image')

        conv1_1 = tf.nn.relu(self.conv2d(self.X_test, [3, 3, 3, 64], 'conv1_1'))
        conv1_2 = tf.nn.relu(self.conv2d(conv1_1, [3, 3, 64, 64], 'conv1_2'))
        pool1 = tf.nn.max_pool(conv1_2, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME', name='pool1')
        conv2_1 = tf.nn.relu(self.conv2d(pool1, [3, 3, 64, 128], 'conv2_1'))
        conv2_2 = tf.nn.relu(self.conv2d(conv2_1, [3, 3, 128, 128], 'conv2_2'))
        pool2 = tf.nn.max_pool(conv2_2, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME', name='pool2')
        conv3_1 = tf.nn.relu(self.conv2d(pool2, [3, 3, 128, 256], 'conv3_1'))
        conv3_2 = tf.nn.relu(self.conv2d(conv3_1, [3, 3, 256, 256], 'conv3_2'))
        conv3_3 = tf.nn.relu(self.conv2d(conv3_2, [3, 3, 256, 256], 'conv3_3'))
        pool3 = tf.nn.max_pool(conv3_3, ksize=[1, 3, 3, 1], strides=[1, 2, 2, 1], padding='SAME', name='pool3')
        conv4_1 = tf.nn.relu(self.conv2d(pool3, [3, 3, 256, 512], 'conv4_1'))
        conv4_2 = tf.nn.relu(self.conv2d(conv4_1, [3, 3, 512, 512], 'conv4_2'))
        conv4_3 = tf.nn.relu(self.conv2d(conv4_2, [3, 3, 512, 512], 'conv4_3'))
        pool4 = tf.nn.max_pool(conv4_3, ksize=[1, 3, 3, 1], strides=[1, 1, 1, 1], padding='SAME', name='pool4')

        conv5_1 = tf.nn.relu(self.astro_conv2d(pool4, [3, 3, 512, 512], hole=2, name='conv5_1'))
        conv5_2 = tf.nn.relu(self.astro_conv2d(conv5_1, [3, 3, 512, 512], hole=2, name='conv5_2'))
        conv5_3 = tf.nn.relu(self.astro_conv2d(conv5_2, [3, 3, 512, 512], hole=2, name='conv5_3'))
        pool5 = tf.nn.max_pool(conv5_3, ksize=[1, 3, 3, 1], strides=[1, 1, 1, 1], padding='SAME')

        fc6 = tf.nn.relu(self.astro_conv2d(pool5, [4, 4, 512, 4096], hole=4, name='fc6'))
        fc6_dropout = tf.nn.dropout(fc6, 0.5)

        fc7 = tf.nn.relu(self.astro_conv2d(fc6_dropout, [1, 1, 4096, 4096], hole=4, name='fc7'))
        fc7_dropout = tf.nn.dropout(fc7, 0.5)

        fc8 = self.conv2d(fc7_dropout, [1, 1, 4096, 1], 'fc8')
        up_fc8 = tf.image.resize_bilinear(fc8, [512, 512])

        pool4_conv = tf.nn.dropout(tf.nn.relu(self.conv2d(pool4, [3, 3, 512, 128], 'pool4_conv')), 0.5)
        pool4_fc = tf.nn.dropout(tf.nn.relu(self.conv2d(pool4_conv, [1, 1, 128, 128], 'pool4_fc')), 0.5)
        pool4_ms_saliency = self.conv2d(pool4_fc, [1, 1, 128, 1], 'pool4_ms_saliency')
        up_pool4 = tf.image.resize_bilinear(pool4_ms_saliency, [512, 512])
        self.final_saliency = tf.sigmoid(tf.add(up_pool4, up_fc8))

        self.init = tf.initialize_all_variables()
        self.saver = tf.train.Saver()


    def load(self):
        self.sess.run(self.init)
        self.saver.restore(self.sess, self.ckpt_dir)


        # conv1 = tf.Variable('conv1_1_w:0')
        # conv2 = tf.get_variable('conv1_2', shape=[3, 3, 64, 64])
        # op = conv1.assign(tf.zeros(shape=[3, 3, 3, 64]))
        # print 'op:', self.sess.run(op)
        # print 'op:', self.sess.run(tf.assign(conv2, tf.zeros(shape=[3, 3, 64, 64], dtype=tf.float32)))

        ######## modify middle layer parameter #############
        # graph = tf.get_default_graph()
        # conv1 = graph.get_tensor_by_name('conv1_1_w:0')
        # op = tf.assign(conv1, tf.zeros(shape=[3, 3, 3, 64], dtype=tf.float32))
        # print 'op:', self.sess.run(op)
        # # print self.sess.run(conv1.initializer)
        # print 'print weights:', conv1.eval()

    def forward(self, image):
        # tf.initialize_all_variables().run()
        # self.sampler(image)
        return self.sess.run(self.final_saliency, feed_dict = {self.X_test: image})



if __name__ == '__main__':
    with tf.Session() as sess:
        # image_dir = '/home/ty/data/MSRA5000/images'
        # label_dir = '/home/ty/data/MSRA5000/GT2'
        # dataset = ImageData(image_dir, label_dir, None, None, '.jpg', '.png', 550, 512, 1, horizontal_flip=False)
        # x, y = dataset.next_batch()

        dcl = DCL(sess, ckpt_dir='fusion_parameter/fusionST_tensorflow.ckpt')
        dcl.train2()
        # dcl.sampler(x)
        # dcl.load()
        # r = dcl.forward(x)
        # plt.imshow(r[0, :, :, 0])
        # plt.show()
        #
        # print np.shape(in_)

        # dcl.load()
        # dcl.train()