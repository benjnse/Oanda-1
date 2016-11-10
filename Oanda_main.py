import threading
import sys
from Oanda_function import *

def main(args):

    if sys.argv[1]=='sche':
        sche=[3, 9, 15, 21]
        timer=60
        shift_scalar=1

        position_dir='C:/Users/Mengfei Zhang/Desktop/fly capital/trading/option_position.csv'
        login_file='C:/Users/Mengfei Zhang/Desktop/fly capital/trading/login_file.csv'

        set_obj=set(timer, sche, shift_scalar, login_file)
        contracts=get_option_position(position_dir, set_obj)

        #start trading
        threads=[]
        for opt in contracts:
            threads.append(threading.Thread(target=opt.start(),args=None))

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

    elif sys.argv[1]=='adhoc':
        sche=[]
        timer=5
        shift_scalar=3

        position_dir='C:/Users/Mengfei Zhang/Desktop/fly capital/trading/option_position_adhoc.csv'
        login_file='C:/Users/Mengfei Zhang/Desktop/fly capital/trading/login_file.csv'

        set_obj=set(timer, sche, shift_scalar, login_file)
        contracts=get_option_position(position_dir, set_obj)

        #start trading
        threads=[]
        for opt in contracts:
            threads.append(threading.Thread(target=opt.start(),args=None))

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

if __name__=='__main__':
    sys.exit(main(sys.argv))

