'''
Prerequisite files:

1) MSCOCO
    go to:
    http://cocodataset.org/#download

    download and unzip:
    - 2014 Train images
    - 2014 Val images
    - 2014 Train/Val annotations

    have this file structure and directories:
    ./data/COCO/annotations/ --> all .json files
    ./data/COCO/train2014/ --> all train images
    ./data/COCO/val2014/ --> all test (val) images
    ./output/COCO

2) Flickr30k
    go to:
    http://shannon.cs.illinois.edu/DenotationGraph/data/index.html

    download and unzip:
    - Flickr 30k images
    - Publicly Distributable Version of the Flickr 30k Dataset
      (tokenized captions only)

    rename:
    - flickr30k-images --> train
    - results_20130124.token --> captions.tsv

    have this file structure and directories:
    ./data/Flickr/annotations/captions.tsv
    ./data/Flickr/train
    ./output/Flickr

---------------------------------

This doc is missing:

1) RNN Class

3) Checkpoint function
4) Trainig loop and parameters
'''

import torch
import torchvision
import torchvision.transforms as tf
import torchvision.models as models
from torch.autograd import Variable
import h5py
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import torch.optim as optim
import random
from pycocotools.coco import COCO  # For MSCOCO dataset
from collections import Counter
import nltk  # For evaluation metrics
# nltk.download('punkt')
import pickle
from itertools import takewhile
from PIL import Image
import torch.utils.data as data
import os
from datetime import datetime
from torchvision.datasets import CocoCaptions  # For MSCOCO dataset captions
import time

dir_path = os.path.dirname(os.path.realpath(__file__))
os.chdir(dir_path)

# Defining the needed paths and parameters for MSCOCO
parameter_dict_MSCOCO = {
    # Data Loader Parameters:
    'batch_size': 32,
    'shuffle': True,
    'num_workers': 0,

    # Directory Info:
    # MSCOCO dataset: stores annotations and images
    'data_dir': './data/COCO',
    # MSCOCO output: Stores model checkpoints and vocab
    'output_dir': './output/COCO',
    # Path for MSCOCO training captions from 'data_dir'
    'train_ann_path': 'annotations/captions_train2014.json',
    # Path for MSCOCO validation captions from 'data_dir'
    'test_ann_path': 'annotations/captions_val2014.json',
    # Vocabulary file name
    'vocabulary_path': 'vocab.pkl',
    # Directory name for the training images in the MSCOCO dataset
    'train_img_dir': 'train2014',
    # Directory name for the validation images in the MSCOCO dataset
    'test_img_dir': 'val2014',
}

# Defining the needed paths and parameters for Flickr
parameter_dict_Flickr = {
    # Data Loader Parameters:
    'batch_size': 32,
    'shuffle': True,
    'num_workers': 0,

    # Directory Info:
    # Flickr dataset: stores annotations and images
    'data_dir': './data/Flickr',
    # Flickr output: Stores model checkpoints and vocab
    'output_dir': './output/Flickr',
    # Path for Flickr training captions from 'data_dir'
    'train_ann_path': 'annotations/captions.tsv',
    # Path for Flickr validation captions from 'data_dir'
    # 'val_ann_path': 'annotations/val_annotations.tsv',
    # Path for Flickr test captions from 'data_dir'
    # 'test_ann_path': 'annotations/test_annotations.tsv',
    # Vocabulary file name
    'vocabulary_path': 'vocab.pkl',
    # Directory name for the training images in the Flickr dataset
    'train_img_dir': 'train',
    # Directory name for the validation images in the Flickr dataset
    'test_img_dir': 'train',
    # Add word to vocabulary only if it appears at least this many times
    'vocab_threshold': 5}


class DatasetVocabulary(object):
    def __init__(self):
        self.word_to_index = {}
        self.index_to_word = {}
        self.index = 0

    def adding_new_word(self, word):
        # Adding a new word to the vocabulary, if it already doesn't exist
        if word not in self.word_to_index:
            self.word_to_index[word] = self.index
            self.index_to_word[self.index] = word
            self.index += 1

    def __call__(self, word):
        if word not in self.word_to_index:
            # If word does not exist in vocabulary, then return unknown token
            return self.word_to_index['<unk>']
        return self.word_to_index[word]

    def __len__(self):
        # Returns the length of the vocabulary
        return len(self.word_to_index)

    def start_token(self):
        # Returns the start token
        return '<start>'

    def end_token(self):
        # Returns the end token
        return '<end>'


# Loading the vocabulary from the vocabulary file
def get_vocab(vocabulary_path):

    if(os.path.isfile(vocabulary_path)):
        # If the file is already craeted and exists, open
        with open(vocabulary_path, 'rb') as f:
            vocabulary = pickle.load(f)
            print('Vocabulary is exists and is loaded.')
    else:
        # Else create the vocabulary file
        print('Vocabulary does not exist. Creating vocab...')
        create_vocabulary(MSCOCO_build = 1, Flickr_build = 0)
        vocabulary = get_vocab(vocabulary_path)

    return vocabulary


# Data loader for the MSCOCO dataset
class MSCOCO(data.Dataset):
    def __init__(self, annotations, data_path, vocabulary, augmentation_tf=None):  # noqa

        # Specifying the path for the datasets
        self.data_path = data_path

        # Defining the vocabulary for the dataset
        self.vocabulary = vocabulary

        # Defining the annotations for the dataset
        self.annotations = annotations

        # Creating a list of the annotation IDs for MSCOCO dataset
        self.annotation_ids = list(COCO(annotations).anns.keys())

        # Specifying the data augmentations on the dataset
        self.augmentation_tf = augmentation_tf

    def __getitem__(self, image_index):
        '''
        Function to retrieve an image and it's
        corresponding caption for the dataset
        '''

        annotations = self.annotations
        vocabulary = self.vocabulary

        # Retrieving the annotation index corresponding to the image index
        annotation_index = self.annotation_ids[image_index]

        # Retrieving the caption corresponding to the image index
        image_caption = COCO(annotations).anns[annotation_index]['caption']

        # Retrieving the image index corresponding to the
        # annotation index from Image index
        image_index = COCO(annotations).anns[annotation_index]['image_id']

        # Recording the path of the image
        image_path = COCO(annotations).loadImgs(image_index)[0]['file_name']

        # Applying the data augmentation transformations on the images
        image = Image.open(os.path.join(
            self.data_path, image_path)).convert('RGB')
        if self.augmentation_tf is not None:
            image = self.augmentation_tf(image)

        # Tokenizing the captions for the image after
        # converting them to lower case
        tokens_caption = nltk.tokenize.word_tokenize(
            str(image_caption).lower())
        image_target_caption = []

        # Starting the caption with <start>
        image_target_caption.append(vocabulary('<start>'))
        image_target_caption.extend([vocabulary(token)
                                     for token in tokens_caption])

        # Ending the caption with <end>
        image_target_caption.append(vocabulary('<end>'))

        # Converting the tokenized caption to a tensor for computations
        image_target_caption = torch.Tensor(image_target_caption)

        # Returning the image and it's
        # corresponding real caption for the index given
        return image, image_target_caption

    def __len__(self):
        '''
        Function returning the length of the dataset
        '''
        return len(self.annotation_ids)


def get_data_transforms():
    '''
    Function to apply data Transformations on the dataset
    '''

    data_trans = tf.Compose([
        # Resize to 224 because we are using pretrained Imagenet
        tf.Resize((224, 224)),
        # Random flipping of images
        tf.RandomHorizontalFlip(),
        tf.RandomVerticalFlip(),
        # Normalizing the images
        tf.ToTensor(),
        tf.Normalize((0.485, 0.456, 0.406),
                     (0.229, 0.224, 0.225))
    ])

    # Returning the  transformed images
    return data_trans


def create_batch(data):
    '''
    Function to create batches from images and it's corresponding real captions
    '''

    # Sorting
    data.sort(key=lambda x: len(x[1]), reverse=True)

    # Retrieving the images and their corresponding captions
    dataset_images, dataset_captions = zip(*data)

    # Stacking the images together
    dataset_images = torch.stack(dataset_images, 0)

    # Writing the lengths of the image captions to a list
    caption_lengths = []
    for caption in dataset_captions:
        caption_lengths.append(len(caption))

    target_captions = torch.zeros(
        len(dataset_captions),
        max(caption_lengths)).long()

    for index, image_caption in enumerate(dataset_captions):
        caption_end = caption_lengths[index]
        # Computing the length of the particular caption for the index
        target_captions[index, :caption_end] = image_caption[:caption_end]

    # Returns the images, captions, and lengths of captions
    return dataset_images, target_captions, caption_lengths


def get_data_loader(annotations_path, data_path, vocabulary, data_tf, parameter_dict):  # noqa
    '''
    Function to load the required dataset in batches
    '''

    dataset = MSCOCO(annotations_path, data_path, vocabulary, data_tf)
    data_loader = torch.utils.data.DataLoader(
        dataset=dataset,
        batch_size=parameter_dict['batch_size'],
        shuffle=parameter_dict['shuffle'],
        num_workers=parameter_dict['num_workers'],
        collate_fn=create_batch)

    return data_loader


def create_caption_word_format(tokenized_version, dataset_vocabulary):
    '''
    Function to convert the tokenized version of sentence
    to a sentence with words from the vocabulary
    '''

    # Defining the start token
    start_word = [dataset_vocabulary.word_to_index[word]
                  for word in [dataset_vocabulary.start_token()]]

    # Defining the end token
    def end_word(index):
        return dataset_vocabulary.index_to_word[index] != dataset_vocabulary.end_token()  # noqa

    # Creating the sentence in list format from the tokenized version
    caption_word_format_list = []
    for index in takewhile(end_word, tokenized_version):
        if index not in start_word:
            caption_word_format_list.append(
                dataset_vocabulary.index_to_word[index])

    # Returns the sentence with words from the vocabulary
    return ' '.join(caption_word_format_list)


class Resnet(nn.Module):
    ''' Class for defining the CNN architecture implemetation'''
    def __init__(self):
        super(Resnet, self).__init__()
        self.resultant_features  = 80
        #Loading the pretrained Resnet model on ImageNet dataset
        #We tried Resnet50/101/152 as architectures
        resnet_model = models.resnet101(pretrained=True)
        self.model = nn.Sequential(*list(resnet_model.children())[:-1])
        #Training only the last 2 layers for the Resnet model i.e. linear and batchnorm layer
        self.linear_secondlast_layer = nn.Linear(resnet_model.fc.in_features, self.resultant_features)
        #Last layer is the 1D batch norm layer
        self.last_layer = nn.BatchNorm1d(self.resultant_features, momentum=0.01)
        #Initializing the weights using normal distribution
        self.linear_secondlast_layer.weight.data.normal_(0,0.05)
        self.linear_secondlast_layer.bias.data.fill_(0)

    def forward(self, input_x):
        ''' Defining the forward pass of the CNN architecture model'''
        input_x = self.model(input_x)
        #Converting to a pytorch variable
        input_x = Variable(input_x.data)
        #Flattening the output of the CNN model
        input_x = input_x.view(input_x.size(0), -1)
        #Applying the linear layer
        input_x = self.last_layer(self.linear_secondlast_layer(input_x))
        return input_x

def main():
    parameter_dict = parameter_dict_MSCOCO
    
    # Defining the path for the vocabulary
    vocabulary_path = os.path.join(
        parameter_dict['output_dir'],
        parameter_dict['vocabulary_path'])

    # Defining the vocabulary
    vocabulary = get_vocab(vocabulary_path)

    # Loading the train loader
    train_data_loader = get_data_loader(
        annotations_path=os.path.join(
            parameter_dict['data_dir'],
            parameter_dict['train_ann_path']),
        data_path=os.path.join(
            parameter_dict['data_dir'],
            parameter_dict['train_img_dir']),
        data_transforms=get_data_transforms(),
        parameter_dict=parameter_dict,
        vocabulary=vocabulary)

if __name__ == "__main__":
    main()
