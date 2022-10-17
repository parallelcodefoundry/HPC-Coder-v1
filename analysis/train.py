''' Train LLM on source code data.
    author: Daniel Nichols
    date: October 2022
'''
# std imports
from argparse import ArgumentParser
from typing import Iterable, Optional, Union
import logging
from os import PathLike, environ
from os.path import isdir
import pickle

# tpl imports
import torch
from datasets import load_dataset, DatasetDict
from tokenizers import Tokenizer
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoModelForMaskedLM
import tqdm

# local imports
from load_dataset import get_source_filenames, get_source_file_size, get_loc, filter_bad_encoding, filter_duplicates, \
    filter_by_size


def get_args():
    ''' Parse the command line arguments and return the object with them as properties.
    '''
    parser = ArgumentParser(description='Train a LLM on source code data')
    parser.add_argument('--log', choices=['INFO', 'DEBUG', 'WARNING', 'ERROR', 'CRITICAL'],
        default='INFO', type=str.upper, help='logging level')
    parser.add_argument('--input', type=str, required=True, help='root of textual source data or path to pkl of ' +
        'filenames list')
    parser.add_argument('--dataset-info', action='store_true', help='show dataset stats')
    parser.add_argument('--cache-fnames', type=str, help='cache the filenames to this path')
    parser.add_argument('--deduplicate', action='store_true', help='If provided, then data will be deduplicated')
    parser.add_argument('--model', type=str, default='gpt2', help='what model to train')
    parser.add_argument('--lm-task', default='causal', choices=['causal', 'masked'], help='LM training objective')
    parser.add_argument('--tokenizer', type=str, default='gpt2', help='what text tokenizer to use')
    parser.add_argument('--max-seq-length', default=1024, help='maximum sequence length')
    return parser.parse_args()


def print_source_file_stats(fnames: Iterable[PathLike]):
    ''' Print meta-data about source files such as # files, LOC, and memory size.

        Args:
            fnames: File names to compute statistics over
    '''
    loc = get_loc(fnames)
    size = get_source_file_size(fnames)

    print('# source files: {:,}'.format(len(fnames)))
    print('LOC: {:,}'.format(loc))
    print('Dataset size: {:.3g} GB'.format(size / (1<<30)))


def get_dataset(dataset_path: PathLike, deduplicate: bool = True, fnames_cache_output: Optional[PathLike] = None,
    print_stats: bool = True) -> DatasetDict:
    ''' Fetch the dataset from dataset_path and return a huggingface DatasetDict object.

        Args:
            dataset_path:
            deduplicate:
            fnames_cache_output: fnames
            print_stats: If true, then print summary statistics of data set.
    '''
    if isdir(dataset_path):
        # read filenames from root
        fnames = get_source_filenames(dataset_path)
        fnames = filter_bad_encoding(fnames)
        fnames = filter_by_size(fnames, max_mb=1, min_tokens=15)

        if fnames_cache_output:
            with open(fnames_cache_output, 'wb') as fp:
                pickle.dump(fnames, fp)
    else:
        # read filenames from pickle
        with open(dataset_path, 'rb') as fp:
            fnames = pickle.load(fp)

    if deduplicate:
        fnames = filter_duplicates(fnames)
    
    if print_stats:
        print_source_file_stats(fnames)
        
    return load_dataset('text', name='HPC-Source-Dataset', data_files=fnames, encoding='utf-8', sample_by='document')
    

def get_model(model_name: Union[str, PathLike], training_task: str = 'causal'):
    ''' Return the pretrained model from file or huggingface.

        Args:
            model_name: name of huggingface model or path to model
            training_task: causal or masked
    '''
    assert training_task in ['causal', 'masked']

    model = None
    if training_task == 'causual':
        model = AutoModelForCausalLM.from_pretrained(model_name)
    elif training_task == 'masked':
        model = AutoModelForMaskedLM.from_pretrained(model_name)

    return model


def train(dataset, model):
    ''' Train model on dataset.

        Args:
            dataset: HuggingFace text dataset
            model: LLM
    '''
    pass


def main():
    args = get_args()

    # setup logging
    numeric_level = getattr(logging, args.log.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: {}'.format(args.log))
    logging.basicConfig(format='%(asctime)s [%(levelname)s] -- %(message)s', 
        level=numeric_level) #filename='log.txt', filemode='w')

    # environment setup
    logging.info('Setting up environment...')
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    environ['TOKENIZERS_PARALLELISM'] = '0'
    #environ['OMP_NUM_THREADS'] = '32'
    #tqdm.tqdm.monitor_interval = 0  # fixes bug where tqdm calls in HF error due to monitor threading
    logging.info('Using device: {}'.format(device))

    # gather and initialize dataset
    logging.info('Creating dataset...')
    dataset = get_dataset(args.input, deduplicate=args.deduplicate, fnames_cache_output=args.cache_fnames,
        print_stats=args.dataset_info)
    print(dataset)
    
    # tokenizer dataset
    logging.info('Tokenizing dataset...')
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer)
    def tokenize_func(x):
        return tokenizer(x["text"], truncation=True, max_length=args.max_seq_length)
    
    tokenized_dataset = dataset.map(tokenize_func, batched=True)
    print(tokenized_dataset)

    # initialize model
    logging.info('Creating model...')
    model = get_model(args.model, training_task = args.lm_task)
    model.to(device)

    # train
    logging.info('Training...')
    train(tokenized_dataset, model)



if __name__ == '__main__':
    main()

