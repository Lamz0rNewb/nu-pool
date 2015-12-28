#! /usr/bin/env python
"""
The MIT License (MIT)
Copyright (c) 2015 creon (creon.nu@gmail.com)
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE
OR OTHER DEALINGS IN THE SOFTWARE.
"""

import os
import sys
import subprocess
import tempfile
import ast
from math import ceil
from utils import *
from random import randint


class NuBot(ConnectionThread):
    def __init__(self, conn, requester, key, secret, exchange, unit, target, logger=None,
                 ordermatch=False, deviation=0.0025, reset_timer=0, offset=0.002):
        super(NuBot, self).__init__(conn, logger)
        self.requester = requester
        self.process = None
        self.unit = unit
        self.target = target
        self.running = False
        self.exchange = exchange
        self.deviation = deviation
        self.reset_timer = reset_timer
        self.offset = offset
        self.options = {
            'exchangename': repr(exchange),
            'apikey': key,
            'apisecret': secret,
            'txfee': 0.2,
            'pair': 'nbt_' + unit,
            'submit-liquidity': False,
            'dualside': True,
            'multiple-custodians': True,
            'executeorders': ordermatch,
            'mail-notifications': False,
            'hipchat': False
        }
        if unit != 'usd':
            if unit == 'btc':
                self.options['secondary-peg-options'] = {
                    'main-feed': 'bitfinex',
                    'backup-feeds': {
                        'backup1': {'name': 'blockchain'},
                        'backup2': {'name': 'coinbase'},
                        'backup3': {'name': 'bitstamp'}
                    }}
            else:
                self.logger.error('no price feed available for %s', unit)
            self.options['secondary-peg-options']['wallshift-threshold'] = 0.3
            self.options['secondary-peg-options']['spread'] = 0.0

    def run(self):
        out = tempfile.NamedTemporaryFile(delete=False)
        out.write(json.dumps({'options': self.options}))
        out.close()
        reset_time = time.time()
        while self.active:
            if float(time.time()) - float(reset_time) > self.reset_timer:
                self.logger.info('reset timer has elapsed. will restart trading bot')
                self.shutdown(True)
            if self.requester.errorflag:
                self.shutdown()
            elif not self.process:
                with open(os.devnull, 'w') as fp:
                    self.logger.info("starting NuBot for %s on %s", self.unit, repr(self.exchange))
                    self.process = subprocess.Popen("java -jar NuBot.jar %s" % out.name,
                                                    stdout=fp, stderr=fp, shell=True, cwd='nubot')
            time.sleep(10)
        self.shutdown()

    def shutdown(self, restart=False):
        if self.process:
            self.logger.info("stopping NuBot for unit %s on %s", self.unit, repr(self.exchange))
            self.process.terminate()
            # os.killpg(self.process.pid, signal.SIGTERM)
            self.process = None
        if restart:
            self.run()


class PyBot(ConnectionThread):
    def __init__(self, conn, requester, key, secret, exchange, unit, target, logger=None, ordermatch=False,
                 deviation=0.0025, reset_timer=0, offset=0.002,
		 shift={'auto':0,'manual':0}, fillamount={'bid':10000,'ask':10000}):
        super(PyBot, self).__init__(conn, logger)
        self.requester = requester
        self.ordermatch = ordermatch
        self.key = key
        self.secret = secret
        self.exchange = exchange
        self.unit = unit
        self.orders = []
        self.target = target.copy()
        self.total = target.copy()
        self.limit = target.copy()
        self.lastlimit = {'bid': 0, 'ask': 0}
        self.deviation = deviation
        self.reset_timer = reset_timer
        self.offset = offset
 	self.shift = shift
	self.placetimer = 0
	self.placetimer2 = 0
	self.fillamount = fillamount
        if not hasattr(PyBot, 'lock'):
            PyBot.lock = {}
        if not repr(exchange) in PyBot.lock:
            PyBot.lock[repr(exchange)] = threading.Lock()
        if not hasattr(PyBot, 'pricefeed'):
            PyBot.pricefeed = PriceFeed(30, logger)

    def cancel_orders(self, side='all', reset=True):
        try:
            response = self.exchange.cancel_orders(self.unit, side, self.key, self.secret)
        except:
            response = {'error': 'exception caught: %s' % sys.exc_info()[1]}
        if 'error' in response:
            self.logger.error('unable to delete %s orders for %s on %s: %s', side, self.unit, repr(self.exchange),
                              response['error'])
            self.exchange.adjust(response['error'])
            self.logger.info('adjusting nonce of %s to %d', repr(self.exchange), self.exchange._shift)
        else:
            self.logger.info('successfully deleted %s orders for %s on %s', side, self.unit, repr(self.exchange))
            if reset:
                if side == 'all':
                    self.limit['bid'] = max(self.total['bid'], 0.5)
                    self.limit['ask'] = max(self.total['ask'], 0.5)
                else:
                    self.limit[side] = max(self.total[side], 0.5)
        return response

    def shutdown(self, restart=False):
        self.logger.info("stopping PyBot for %s on %s", self.unit, repr(self.exchange))
        trials = 0
        while trials < 10:
            response = self.cancel_orders(reset=False)
            if not 'error' in response: break
            trials += 1
        if restart:
            self.run()

    def acquire_lock(self):
        PyBot.lock[repr(self.exchange)].acquire()

    def release_lock(self):
        PyBot.lock[repr(self.exchange)].release()

    def balance(self, exunit, price):
        try:
            response = self.exchange.get_balance(exunit, self.key, self.secret)
            if not 'error' in response:
                response['balance'] = response['balance'] if exunit == 'nbt' else response['balance'] / price
                response['balance'] = int(response['balance'] * 10 ** 3) / float(10 ** 3)
        except KeyboardInterrupt:
            raise
        except:
            response = {'error': 'exception caught: %s' % sys.exc_info()[1]}
        return response

    def place(self, side, price):
        if side == 'ask':
            exunit = 'nbt'
            prounit = self.unit
        else:
            exunit = self.unit
            prounit = 'nbt'
        order_response = self.conn.get(self.key, trials=1)
	fullask = 0
	fullbid = 0
        if 'error' in order_response:
            self.logger.error('unable to receive statistics for user %s: %s', self.key,
                                                      order_response['message'])
            self.logger.info('Ignoring fillamount')
            empty = 10000
	else:
            if self.unit in order_response['units']:
                for orders in order_response['units'][self.unit]['ask']:
                    fullask += orders['amount']
            if self.unit in order_response['units']:
                for orders in order_response['units'][self.unit]['bid']:
                    fullbid += orders['amount']
        if side == 'ask':
            empty = ast.literal_eval(self.fillamount)['ask'] - fullask
            if time.time() - self.placetimer < 105:
                empty = 0
	else:
            empty = ast.literal_eval(self.fillamount)['bid'] - fullbid
            if time.time() - self.placetimer2 < 105:
                empty = 0
        shift = abs(ast.literal_eval(self.shift)['auto'])
        response = self.balance(exunit, price)
        response2 = self.balance(prounit, price)
        if 'error' in response:
            self.logger.error('unable to receive balance for %s on %s: %s', exunit, repr(self.exchange),
                              response['error'])
            self.exchange.adjust(response['error'])
            self.logger.info('adjusting nonce of %s to %d', repr(self.exchange), self.exchange._shift)
        elif 'error' in response2:
            self.logger.error('unable to receive balance for %s on %s: %s', prounit, repr(self.exchange),
                              response['error'])
            self.exchange.adjust(response['error'])
            self.logger.info('adjusting nonce of %s to %d', repr(self.exchange), self.exchange._shift)
        elif response['balance'] > 0.1:
            if side == 'ask':
                sumask = response['balance'] + fullask
                sumbid = response2['balance'] + fullbid
                sumtot = sumask + sumbid
                price = price * (1 + shift * (1 - 2*sumask/sumtot) )
            if side == 'bid':
                sumask = response2['balance'] + fullask
                sumbid = response['balance'] + fullbid
                sumtot = sumask + sumbid
                price = price * (1 + shift * (1 - 2*sumask/sumtot) )
                try:
                    response = self.balance(exunit, price)
                except:
                    response['balance'] = response['balance'] / (1 + shift * (1 - 2*sumask/sumtot) )
            amount = min(self.limit[side], response['balance'], empty)
            if amount >= 0.5:
                try:
                    response = self.exchange.place_order(self.unit, side, self.key, self.secret, amount, price)
                except KeyboardInterrupt:
                    raise
                except:
                    response = {'error': 'exception caught: %s' % sys.exc_info()[1]}
                if 'error' in response:
                    if 'residual' in response and response['residual'] > 0:
                        self.limit[side] += response['residual']
                    else:
                        self.logger.error('unable to place %s %s order of %.4f nbt at %.8f on %s: %s',
                                          side, self.unit, amount, price, repr(self.exchange), response['error'])
                    self.exchange.adjust(response['error'])
                else:
                    self.logger.info('successfully placed %s %s order of %.4f nbt at %.8f on %s',
                                     side, self.unit, amount, price, repr(self.exchange))
                    self.orders.append(response['id'])
                    self.limit[side] -= amount
		    if side == 'ask':
			self.placetimer = time.time()
                    else:
                        self.placetimer2 = time.time()
        return response

    def place_orders(self):
        try:
            response = self.exchange.get_price(self.unit)
        except:
            response = {'error': 'exception caught: %s' % sys.exc_info()[1]}
        if 'error' in response:
            self.logger.error('unable to retrieve order book for %s on %s: %s', self.unit, repr(self.exchange),
                              response['error'])
        else:
            spread = max(self.exchange.fee, float(self.offset))
	    manualshift = ast.literal_eval(self.shift)['manual']
            bidprice = ceil(self.price * (1.0 - spread + manualshift) * 10 ** 8) / float(
                10 ** 8)  # truncate floating point precision after 8th position
            askprice = ceil(self.price * (1.0 + spread + manualshift) * 10 ** 8) / float(10 ** 8)
            if response['ask'] is None or response['ask'] > bidprice:
                self.place('bid', bidprice)
            else:
                if self.ordermatch:
                    self.logger.warning('matching ask %s order at %.8f on %s', self.unit, response['ask'],
                                        repr(self.exchange))
                    self.place('bid', bidprice)
                elif 1.0 - response['ask'] / bidprice < 0.00425 - spread:
                    devprice = ceil(bidprice * (1.0 - 0.0045 + spread) * 10 ** 8) / float(10 ** 8)
                    self.logger.debug('decreasing bid %s order at %.8f on %s to %.8f to avoid order match', self.unit,
                                      bidprice, repr(self.exchange), devprice)
                    self.place('bid', devprice)
                elif self.lastlimit['bid'] != self.limit['bid']:
                    self.logger.error('unable to place bid %s order at %.8f on %s: matching order at %.8f detected',
                                      self.unit, bidprice, repr(self.exchange), response['ask'])
            if response['bid'] == None or response['bid'] < askprice:
                self.place('ask', askprice)
            else:
                if self.ordermatch:
                    self.logger.warning('matching bid %s order at %.8f on %s', self.unit, response['bid'],
                                        repr(self.exchange))
                    self.place('ask', askprice)
                elif 1.0 - askprice / response['bid'] < 0.00425 - spread:
                    devprice = ceil(askprice * (1.0045 - spread) * 10 ** 8) / float(10 ** 8)
                    self.logger.debug('increasing ask %s order at %.8f on %s to %.8f to avoid order match', self.unit,
                                      askprice, repr(self.exchange), devprice)
                    self.place('ask', devprice)
                elif self.lastlimit['ask'] != self.limit['ask']:
                    self.logger.error('unable to place ask %s order at %.8f on %s: matching order at %.8f detected',
                                      self.unit, askprice, repr(self.exchange), response['bid'])
            self.lastlimit = self.limit.copy()
        self.requester.submit()

    def sync(self, trials=3):
        ts = int(time.time() * 1000.0)
        response = self.conn.get('sync', trials=1, timeout=15)
        if not 'error' in response:
            delay = (response['sync'] - (response['time'] % response['sync'])) - (int(time.time() * 1000.0) - ts) / 2
            if delay <= 0:
                self.logger.error("unable to synchronize time with server for %s on %s: time difference to small",
                                  self.unit, repr(self.exchange))
                if trials > 0:
                    return self.sync(trials - 1)
            self.logger.info("waiting %.2f seconds to synchronize with other trading bots for %s on %s", delay / 1000.0,
                             self.unit, repr(self.exchange))
            time.sleep(delay / 1000.0)
        elif trials > 0:
            self.logger.error("unable to synchronize time with server for %s on %s: %s", self.unit, repr(self.exchange),
                              response['message'])
            return self.sync(trials - 1)
        else:
            return False
        return True

    def run(self):
        self.logger.info("starting PyBot for %s on %s", self.unit, repr(self.exchange))
        self.serverprice = self.conn.get('price/' + self.unit, trials=3, timeout=15)['price']
        self.price = self.serverprice
        trials = 0
        while trials < 10:
            response = self.cancel_orders(reset=False)
            if 'error' not in response:
                break
            trials += 1
        self.sync()
        self.place_orders()
        curtime = time.time()
        efftime = curtime
        lasttime = curtime
        reset_time = curtime
        lastdev = {'bid': 1.0, 'ask': 1.0}
        delay = 0.0
	maxamount = ast.literal_eval(self.fillamount)
        while self.active:
            if float(time.time()) - float(reset_time) > ((float(
                    self.reset_timer) * 60 + randint(0,9)) * 60) and float(self.reset_timer) > 0:
                self.logger.info('reset timer has elapsed. will restart trading bot')
                python = sys.executable
                os.execl(python, python, * sys.argv)
            try:
                sleep = 30 - time.time() + curtime
                if sleep < 0:
                    delay += abs(sleep)
                    if delay > 5.0:
                        self.logger.warning(
                            'need to resynchronize trading bot for %s on %s because the deviation reached %.2f',
                            self.unit, repr(self.exchange), delay)
                        if self.sync():
                            delay = 0.0
                            if not self.requester.errorflag:
                                self.place_orders()
                else:
                    while sleep > 0:
                        step = min(sleep, 0.5)
                        time.sleep(step)
                        if not self.active:
                            break
                        sleep -= step
                if not self.active:
                    break
                curtime = time.time()
                lasttime = curtime
                if self.requester.errorflag:
                    self.logger.error('server unresponsive for %s on %s', self.unit, repr(self.exchange))
                    self.shutdown()
                    self.limit = self.target.copy()
                    efftime = curtime
                else:
                    response = self.conn.get('price/' + self.unit, trials=3, timeout=10)
                    if 'error' not in response:
                        self.serverprice = response['price']
                        userprice = PyBot.pricefeed.price(self.unit)
                        if 1.0 - min(self.serverprice, userprice) / max(self.serverprice,
                                                                        userprice) > 0.005:  # validate server price
                            self.logger.error(
                                'server price %.8f for %s deviates too much from price %.8f received from ticker, will try to delete orders on %s',
                                self.serverprice, self.unit, userprice, repr(self.exchange))
                            self.price = self.serverprice
                            self.cancel_orders()
                            efftime = curtime
                        else:
                            deviation = 1.0 - min(self.price, self.serverprice) / max(self.price, self.serverprice)
                            if deviation > float(self.deviation):
                                self.logger.info('price of %s moved from %.8f to %.8f, will try to delete orders on %s',
                                                 self.unit, self.price, self.serverprice, repr(self.exchange))
                                self.price = self.serverprice
                                self.cancel_orders()
                                self.place_orders()
                                efftime = curtime
                                continue
                            elif curtime - efftime > 60:
                                efftime = curtime
                                response = self.conn.get(self.key, trials=1)
                                if 'error' in response:
                                    self.logger.error('unable to receive statistics for user %s: %s', self.key,
                                                      response['message'])
                                else:
                                    if self.unit not in response['units']:
                                        response['units'][self.unit] = { 'bid': [], 'ask': [] }
                                    for side in ['bid', 'ask']:
                                        effective_rate = 0.0
                                        effective_rate = float(
                                            sum([o['amount'] * o['cost'] for o in response['units'][self.unit][side]]))
                                        self.total[side] = float(
                                            sum([o['amount'] for o in response['units'][self.unit][side]]))
                                        contrib = float(sum([o['amount'] for o in response['units'][self.unit][side] if
                                                             o['cost'] > 0.0]))
                                        if self.total[side] < 0.5:
                                            self.limit[side] = min(self.limit[side] + 0.5, self.target[side])
                                        else:
                                            effective_rate /= self.total[side]
                                            deviation = 1.0 - min(effective_rate, self.requester.cost[side]) / max(
                                                effective_rate, self.requester.cost[side])
                                            if deviation > 0.02 and lastdev[side] > 0.02:
                                                if self.total[side] > 0.5 \
                                                        and effective_rate < self.requester.cost[side]:
                                                    funds = max(0.5, self.total[side] * (1.0 - max(deviation, 0.1)) and effective_rate != 0)
                                                    self.logger.info(
                                                        "decreasing tier 1 %s limit of %s on %s from %.8f to %.8f",
                                                        side, self.unit, repr(self.exchange), self.total[side], funds)
                                                    self.cancel_orders(side)
                                                    self.limit[side] = funds
                                                elif self.limit[side] < self.total[side] * deviation \
                                                        and effective_rate > self.requester.cost[side] \
                                                        and contrib < self.target[side] \
							and contrib < 0.9*maxamount[side]:
                                                    self.logger.info(
                                                        "increasing tier 1 %s limit of %s on %s from %.8f to %.8f",
                                                        side, self.unit, repr(self.exchange), self.total[side],
                                                        self.total[side] + max(1.0, max(contrib * deviation, 0.5)))
                                                    self.cancel_orders(side)
                                                    self.limit[side] = self.total[side] + max(1.0, max(contrib * deviation, 0.5))
                                            elif 0 < deviation < 0.01 \
                                                    and lastdev[side] < 0.01 \
                                                    and self.limit[side] < max(1.0, max(contrib * deviation, 0.5)) \
                                                    and contrib < self.target[side] \
						    and contrib < 0.9*maxamount[side] \
                                                    and effective_rate >= self.requester.cost[side]:
                                                self.limit[side] = max(1.0, max(contrib * deviation, 0.5))
                                                self.logger.info(
                                                    "increasing tier 1 %s limit of %s on %s from %.8f to %.8f",
                                                    side, self.unit, repr(self.exchange), self.total[side],
                                                    self.total[side] + self.limit[side])
                                                self.cancel_orders(side)
                                                self.limit[side] = self.total[side] + self.limit[side]
                                            lastdev[side] = deviation
                            self.place_orders()
                    else:
                        self.logger.error('unable to retrieve server price: %s', response['message'])
            except Exception as e:
                self.logger.debug('exception caught in trading bot: %s', sys.exc_info()[1])
        time.sleep(1)  # this is to ensure that the order book is updated
        self.shutdown()
