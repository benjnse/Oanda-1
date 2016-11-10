from pyoanda import Order, Client, TRADE
import collections
import math
import csv
from datetime import datetime
import time
import threading
import numpy as np
from scipy.optimize import minimize
from scipy.stats import norm
import smtplib
from email.mime.text import MIMEText
from Oanda_model import *
import sys

sys.setrecursionlimit(99999999)


def datecov2(date):
    date=str(date)
    return date[0:4]+date[5:7]+date[8:10]

class option:

    def __init__(self, underlying, K, mat_date, strategy, notional, buy_sell, set_obj):
        run_time=time.strftime("%Y%m%d_%H%M%S")
        log_dir='C:/Users/Mengfei Zhang/Desktop/fly capital/trading/option log'
        #log_dir='/Users/MengfeiZhang/Desktop/tmp'
        self.client=None
        self.K=K
        self.mat_date=mat_date #yyyymmdd
        self.T=0
        self.S=0
        self.last_price=0
        self.underlying=underlying
        self.strategy=strategy
        self.strategy_dir=[]
        self.notional=notional
        self.model=None
        self.buy_sell=buy_sell
        self.f=open(log_dir+'/'+self.underlying+'_log_'+run_time+'.txt','w')
        self.manually_close=False
        self.locker=threading.Lock()
        self.now=None
        self.updated=False
        self.update_count=0
        self.restart=True
        self.set_obj=set_obj
        self.weekday=None
        # connect
        self.connect()
        # get static data
        self.int_rate=self.get_interest_rate()
        sabr_calib=SABRcalib(0.5, self.T)
        sabr_calib.calib(self.get_hist_data(262*5))
        self.SABRpara=sabr_calib.get_para()

    def connect(self):
        try:
            self.client = Client(
                environment=TRADE,
                account_id=self.set_obj.get_account_id(),
                access_token=self.set_obj.get_token()
            )
            print self.underlying+' connection succeeded...'
        except:
            print self.underlying+' connection failed...'
            time.sleep(5)
            self.connect()

    def get_underlying_price(self):
        try:
            price_resp=self.client.get_prices(instruments=self.underlying, stream=False) #, stream=True
            price_resp=price_resp['prices'][0]
            return (price_resp['ask']+price_resp['bid'])/2
        except Exception as err:
            print >>self.f, err

    def get_hist_data(self, hist_len):
        hist_resp=self.client.get_instrument_history(
            instrument=self.underlying,
            candle_format="midpoint",
            granularity="D",
            count=hist_len,
        )
        price=[]
        for i in range(0,len(hist_resp['candles'])):
            price.append(hist_resp['candles'][i]['closeMid'])

        return price

    def get_hist_vol(self):

        hist_resp=self.client.get_instrument_history(
            instrument=self.underlying,
            candle_format="midpoint",
            granularity="D",
            count=90,
        )

        ret_tmp=[]
        for i in range(1,len(hist_resp['candles'])):
            ret_tmp.append(math.log(hist_resp['candles'][i]['closeMid']/hist_resp['candles'][i-1]['closeMid']))

        return np.std(ret_tmp)*math.sqrt(262)

    def get_atm_vol(self):
        return self.SABRpara[0]*self.get_underlying_price()**(self.SABRpara[1]-1)

    def get_intraday_vol(self):

        return self.get_atm_vol()/math.sqrt(262)

    def get_option_value(self):
        price=0
        for i in range(0,len(self.model)):
            price+=self.model[i].price(self.S, self.int_rate['ccy2'], self.int_rate['ccy1'], self.SABRpara)*self.strategy_dir[i]
        return price

    def get_option_delta(self):
        delta=0
        for i in range(0,len(self.model)):
            delta+=self.model[i].delta(self.S, self.int_rate['ccy2'], self.int_rate['ccy1'], self.SABRpara)*self.strategy_dir[i]

        return delta


    def load_data(self):
        delta_t=datetime.strptime(self.mat_date,'%Y%m%d')-datetime.strptime(datecov2(datetime.today()),'%Y%m%d')
        self.T=float(delta_t.days)/float(365)+0.000001 #prevent expiry date error
        self.now=datetime.now()
        self.weekday=datetime.today().weekday()
        self.S=self.get_underlying_price()
        if self.strategy=='call' or self.strategy=='put':
            self.model=[SABRmodel(self.K[0], self.T, self.strategy)]
            self.strategy_dir=[1]
        elif self.strategy=='straddle':
            self.model=[SABRmodel(self.K[0], self.T, 'call'), SABRmodel(self.K[0], self.T, 'put')]
            self.strategy_dir=[1,1]
        elif self.strategy=='call_spread':
            self.model=[SABRmodel(self.K[0], self.T, 'call'), SABRmodel(self.K[1], self.T, 'call')]
            self.strategy_dir=[1,-1]
        elif self.strategy=='put_spread':
            self.model=[SABRmodel(self.K[0], self.T, 'put'), SABRmodel(self.K[1], self.T, 'put')]
            self.strategy_dir=[1,-1]

    def get_position(self):
        try:
            resp=self.client.get_position(instrument=self.underlying)
            return resp
        except Exception as err:
            if ('Connection' in str(err))==False:
                return None
            else:
                return 0

    def get_pos_dir(self, position):
        if self.buy_sell=='buy':
            if position>=0:
                return 'buy'
            else:
                return 'sell'
        else:
            if position>=0:
                return 'sell'
            else:
                return 'buy'

    def get_trd_dir(self, position_diff):
        if position_diff>=0:
            return 'buy'
        else:
            return 'sell'

    def get_interest_rate(self):
        interest={}
        ccy1=self.underlying[0:3]
        ccy2=self.underlying[4:7]
        resp=self.client.get_instruments(self.underlying, 'interestRate')
        resp_int=resp['instruments'][0]['interestRate']
        interest['ccy1']=(resp_int[ccy1]['ask']+resp_int[ccy1]['bid'])/2
        interest['ccy2']=(resp_int[ccy2]['ask']+resp_int[ccy2]['bid'])/2

        return interest

    def start(self): #start trading
        self.load_data()
        if (int(self.weekday)==4 and int(self.now.hour)>=17): #Friday 5pm
            print 'market closed...'
            return None

        if self.T<=0:
            if self.get_position()!=None: #if there is position open
                resp_expiry=self.client.close_position(instrument=self.underlying)
                send_hotmail('Option expired('+self.underlying+')', resp_expiry, self.set_obj)

            print >> self.f, 'option has expired...'
            return None

        try:
            print 'heartbeat('+self.underlying+') '+str(datetime.now())+'...'
            if self.get_position()==None:
                if self.manually_close==False:
                    print >>self.f,'position '+'('+self.underlying+')'+' does not exist, creating new position...'
                    self.manually_close=True
                    position=int(self.get_option_delta()*self.notional)

                    order = Order(
                        instrument=self.underlying,
                        units=abs(position),
                        side=self.get_pos_dir(position),
                        type="market",
                    )
                    try:
                        resp_order = self.client.create_order(order=order)
                        self.last_price=self.S #update last price
                        print >>self.f,'Order placed: ', resp_order
                        send_hotmail('New position opened('+self.underlying+')', resp_order, self.set_obj)
                    except Exception as err:
                        print >>self.f, err
                        if ('halt' in str(err))==True:
                            print 'market closed...'
                            return None
                        else:
                            print "order not executed..."
                            self.manually_close=False

                    print >>self.f,'price'+'('+self.underlying+')'+'= '+str(self.get_underlying_price())
                    print >>self.f,'delta= '+str(self.get_option_delta())
                    print >>self.f,'T= '+str(self.T)
                    print >>self.f,'SABR parameters: '+str(self.SABRpara)
                    print >>self.f,'ATM volatility: '+str(self.get_atm_vol())
                    print >>self.f,'interest rate '+ str(self.int_rate)
                    print >>self.f,self.get_pos_dir(position)+' '+str(abs(position))+' '+self.underlying
                    print >>self.f, 'current total position is: '+self.get_position()['side']+' '+str(self.get_position()['units'])+' '+self.underlying
                    print >>self.f,self.now.strftime("%Y-%m-%d %H:%M:%S")
                    print >>self.f,'------------------------------------------------------------'
                elif self.manually_close==True and self.get_position()==None: #in case fake close position
                    print 'position ('+self.underlying+') has been manually closed...'
                    return None

            elif self.get_position()['units']>self.notional:

                resp=self.client.close_position(instrument=self.underlying)
                print >>self.f, resp
                print >>self.f, 'unusual amount of position openned, position closed...'
                return None

            else:
                if self.last_price==0:
                    self.last_price=self.S
                ret=math.log(self.S/self.last_price)

                if abs(ret)>=3*self.get_intraday_vol():
                    send_hotmail('3 Std move('+self.underlying+')', {'msg ':str(ret/self.get_intraday_vol())}, self.set_obj)

                position=self.get_option_delta()*self.notional
                current_position=self.get_position()['units']
                current_dir=self.get_position()['side']

                if current_dir=='sell':
                    current_position=-current_position
                if self.buy_sell=='sell':
                    position=-position

                position_diff=int(position-current_position)
                #schedule
                if  (int(self.now.hour) in self.set_obj.get_sche())==True:
                    if self.updated==False:
                        self.updated=True
                        self.update_count+=1
                    else:
                        self.update_count+=1
                else: #past schedule, reset parameters
                    self.updated=False
                    self.update_count=0

                if (abs(ret)>self.get_intraday_vol()/self.set_obj.get_shift_scalar() and abs(ret)<3*self.get_intraday_vol()) or (self.updated==True and self.update_count==1) or self.restart==True:
                    print >>self.f,'position '+'('+self.underlying+')'+' already exists, adjusting position...'
                    if self.restart==True:
                        print >> self.f, 'position restarted..'
                        msg_title='Restart position'
                        if position_diff==0:
                            position_diff=1
                        self.restart=False
                        self.manually_close=True
                    elif self.updated==True:
                        print >> self.f, 'position updated in force...'
                        msg_title='Scheduled rebalance'
                        if position_diff==0:
                            position_diff=1
                    else:
                        print >> self.f, 'price movement > 1 std'
                        if ret>0:
                            msg_title='Big price move(+)'
                        else:
                            msg_title='Big price move(-)'

                    order = Order(
                        instrument=self.underlying,
                        units=abs(position_diff),
                        side=self.get_trd_dir(position_diff),
                        type="market",
                    )
                    try:
                        resp_order = self.client.create_order(order=order)
                        self.last_price=self.S
                        print >>self.f,'Order placed: ', resp_order
                        send_hotmail(msg_title+'('+self.underlying+')', resp_order, self.set_obj)
                    except Exception as err:
                        print >>self.f, err
                        if ('halt' in str(err))==True:
                            print 'market closed...'
                            return None
                        else:
                            print "order not executed..."
                            self.manually_close=False

                    print >>self.f,'price'+'('+self.underlying+')'+'= '+str(self.get_underlying_price())
                    print >>self.f,'delta= '+str(self.get_option_delta())
                    print >>self.f,'T= '+str(self.T)
                    print >>self.f,'SABR parameters: '+str(self.SABRpara)
                    print >>self.f,'ATM volatility: '+str(self.get_atm_vol())
                    print >>self.f,'interest rate '+ str(self.int_rate)
                    print >>self.f,self.get_trd_dir(position_diff)+' '+str(abs(position_diff))+' '+self.underlying
                    print >>self.f, 'current total position is: '+self.get_position()['side']+' '+str(self.get_position()['units'])+' '+self.underlying
                    print >>self.f,self.now.strftime("%Y-%m-%d %H:%M:%S")
                    print >>self.f,'------------------------------------------------------------'

                else: #if difference is small
                    print >>self.f,'diff less than 1 std, order will not be send...'
                    print >>self.f,'current total position is: '+self.get_position()['side']+' '+str(self.get_position()['units'])+' '+self.underlying
                    print >>self.f,self.now.strftime("%Y-%m-%d %H:%M:%S")
                    print >>self.f,'------------------------------------------------------------'
        except:
            print self.underlying+' disconnected, try to reconnect '+str(datetime.now())+'...'
            self.connect()

        threading.Timer(self.set_obj.get_timer(), self.start).start()


def get_option_position(fileName_, set_obj):
    contracts=[]
    file = open(fileName_, 'r')
    try:
        reader = csv.reader(file)
        for row in reader:
            ccy=row[0]
            maturity=str(row[1])
            deal_type=row[2]
            notional=int(row[3])
            side=row[4]
            if ('spread' in deal_type) != True:
                strike=[float(row[5])]
                contracts.append(option(ccy, strike, maturity, deal_type, notional, side, set_obj))
            elif ('spread' in deal_type) == True:
                strike=[float(row[5]),float(row[6])]
                contracts.append(option(ccy, strike, maturity, deal_type, notional, side, set_obj))
            else:
                print 'unknown deal type...'

    finally:
        file.close()
    return contracts

def send_hotmail(subject, content, set_obj):
    msg_txt=format_email_dict(content)
    from_email={'login': set_obj.get_email_login(), 'pwd': set_obj.get_email_pwd()}
    to_email='finatos@me.com'

    msg=MIMEText(msg_txt)
    msg['Subject'] = subject
    msg['From'] = from_email['login']
    msg['To'] = to_email
    mail=smtplib.SMTP('smtp.live.com',25)
    mail.ehlo()
    mail.starttls()
    mail.login(from_email['login'], from_email['pwd'])
    mail.sendmail(from_email['login'], to_email, msg.as_string())
    mail.close()


def format_email_dict(content):
    content_tmp=''
    for item in content.keys():
        content_tmp+=str(item)+':'+str(content[item])+'\r\n'
    return content_tmp


class set:
    def __init__(self, timer, sche, shift_scalar, login_file):
        self.timer=timer
        self.sche=sche
        self.shift_scalar=shift_scalar

        file = open(login_file, 'r')
        i=1
        try:
            reader = csv.reader(file)
            for row in reader:
                if i==1:
                    self.account_id=row[0]
                elif i==2:
                    self.token=row[0]
                elif i==3:
                    self.email_login=row[0]
                elif i==4:
                    self.email_pwd=row[0]
                i+=1

        finally:
            file.close()

    def get_timer(self):
        return self.timer

    def get_sche(self):
        return self.sche

    def get_account_id(self):
        return str(self.account_id)

    def get_token(self):
        return str(self.token)

    def get_email_login(self):
        return str(self.email_login)

    def get_email_pwd(self):
        return str(self.email_pwd)

    def get_shift_scalar(self):
        return self.shift_scalar




