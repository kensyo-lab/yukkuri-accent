# Python が入っているPCでは、このファイルをダブルクリックすると
# 黒いコンソール画面を出さずに起動できます。
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from accent_app import main

main()
