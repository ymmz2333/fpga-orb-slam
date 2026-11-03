"""Inspect an existing compiled graph without rerunning the compiler."""
import argparse
from pathlib import Path
from .placement import inspect_xmodel

def main():
    p=argparse.ArgumentParser()
    for key in ['model','source','output']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();print(inspect_xmodel(**vars(a)))

if __name__=='__main__':main()
