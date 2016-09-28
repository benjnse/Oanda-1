import threading
from Oanda_function import *

#main
option_position_dir='C:/Users/Mengfei Zhang/Desktop/fly capital/trading/option_position.csv'
contracts=get_option_position(option_position_dir)

#start trading
threads=[]
for opt in contracts:
    threads.append(threading.Thread(target=opt.start(),args=None))

for thread in threads:
    thread.start()

for thread in threads:
    thread.join()

