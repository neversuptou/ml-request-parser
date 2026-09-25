"""python cli.py post.txt   (или текст в stdin)"""
import sys

from parser.extractor import extract, render

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as fh:
            text = fh.read()
    else:
        sys.stdin.reconfigure(encoding="utf-8")
        text = sys.stdin.read()
    print(render(extract(text)))
