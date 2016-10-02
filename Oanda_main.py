import threading
from Oanda_function import *

#main
option_position_dir='/Users/MengfeiZhang/Desktop/tmp/option_position.csv'
login_file='/Users/MengfeiZhang/Desktop/tmp/login_info.csv'
sche=[(3,1), (9,1), (18,35), (21,1)]
timer=60

set_obj=set_obj(timer, sche, login_file)
contracts=get_option_position(option_position_dir, set_obj)

#start trading
threads=[]
for opt in contracts:
    threads.append(threading.Thread(target=opt.start(),args=None))

for thread in threads:
    thread.start()

for thread in threads:
    thread.join()

