#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
#    BTC: 13MXa7EdMYaXaQK6cDHqd4dwr2stBK3ESE
#    LTC: LfxwJHNCjDh2qyJdfu22rBFi2Eu8BjQdxj
#
#    https://github.com/s4w3d0ff/marconibot
#
#    Copyright (C) 2017  https://github.com/s4w3d0ff
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
from ..tools import (getMongoColl, logging, time, pd,
                     pymongo, RD, GR, sleep, Thread)
from ..trading import StopLimit
from .. import indicators


logger = logging.getLogger(__name__)


class Market(object):
    """
    Market object

    Maintains/Returns database entries for a market, as well as provides
    convienance methods for common functions done on markets.

    >>> from marconi.poloniex import Poloniex
    >>> from marconi.market import Market
    >>> m = Market(Poloniex(), 'BTC_LTC')
    >>> m.tick
    Ticker is not running!
    {'lowestAsk': '0.01186207',
     'percentChange': '0.01107987',
     'last': '0.01186207',
     'low24hr': '0.01162001',
     'isFrozen': '0',
     'baseVolume': '2447.88320868',
     'quoteVolume': '206723.01766984',
     'high24hr': '0.01216872',
     'highestBid': '0.01186206',
     'id': 50.0}
    >>> m.api.startWebsocket()
    >>> m.tick
    {'lowestAsk': 0.01184702,
     'percentChange': 0.00843037,
     'last': 0.01184703,
     'low24hr': 0.01162001,
     'isFrozen': 0.0,
     'baseVolume': 2450.68462713,
     'quoteVolume': 206959.32500459,
     'high24hr': 0.01216872,
     'highestBid': 0.01184379,
     'id': 50.0}
    >>> m.tick
    {'lowestAsk': 0.01184702,
     'percentChange': 0.00868624,
     'last': 0.01184702,
     'low24hr': 0.01162001,
     'isFrozen': 0.0,
     'baseVolume': 2450.68462713,
     'quoteVolume': 206959.32500459,
     'high24hr': 0.01216872,
     'highestBid': 0.01184363,
     'id': 50.0}
    >>> m.api.stopWebsocket()
    >>> m.tick
    Ticker is not running!
    {'lowestAsk': '0.01184703',
     'percentChange': '0.00949332',
     'last': '0.01184703',
     'low24hr': '0.01162001',
     'isFrozen': '0',
     'baseVolume': '2451.57755359',
     'quoteVolume': '207034.66196856',
     'high24hr': '0.01216872',
     'highestBid': '0.01184702',
     'id': 50.0}
    >>>
    """

    def __init__(self, api, pair):
        self.api = api
        self.api.jsonNums = float
        self.parent, self.child = pair.split('_')
        self.pair = pair
        self.stops = []

    @property
    def tick(self):
        """
        Get a market 'tick'
        """
        return self.api.marketTick(self.pair)

    @property
    def availBalances(self):
        """
        Get available balances from poloniex
        """
        bals = self.api.returnCompleteBalances('exchange')
        childBal = float(bals[self.child]['available'])
        parentBal = float(bals[self.parent]['available'])
        logger.debug('Balances: %s [%s] %.8f [%s] %.8f',
                     self.pair, self.parent, parentBal, self.child, childBal)
        return parentBal, childBal

    @property
    def openOrders(self):
        """ Get open orders from poloniex """
        return self.api.returnOpenOrders(self.pair)

    def chart(self, start=False, zoom=False, indica={}):
        """ returns chart data in a dataframe from mongodb, updates/fills the
        data, the date column is the '_id' of each candle entry, and
        the date column has been removed. Use 'start' to restrict the amount
        of data returned.
        Example: 'start=time() - api.YEAR' will return last years data
        """
        if not start:
            start = time() - self.api.YEAR * 1
        dbcolName = self.pair + '-chart'
        # get db connection
        db = getMongoColl('poloniex', dbcolName)
        # get last candle
        try:
            last = list(db.find({"_id": {
                "$gt": time() - self.api.WEEK * 2
            }}).sort('timestamp', pymongo.ASCENDING))[-1]
        except:
            last = False
        logger.info('Getting new candles from Poloniex')
        # no entrys found, get all 5min data from poloniex
        if not last:
            logger.warning('%s collection is empty!', dbcolName)
            new = self.api.returnChartData(self.pair,
                                           period=60 * 5,
                                           start=time() - self.api.YEAR * 13)
        else:
            new = self.api.returnChartData(self.pair,
                                           period=60 * 5,
                                           start=int(last['_id']))
        # add new candles
        updateSize = len(new)
        logger.info('Updating %s with %s new entrys!',
                    dbcolName, str(updateSize))
        for i in range(updateSize):
            date = new[i]['date']
            del new[i]['date']
            db.update_one({'_id': date}, {"$set": new[i]}, upsert=True)
        logger.debug('Getting chart data from db')
        # make dataframe
        df = pd.DataFrame(list(db.find({"_id": {"$gt": start}}
                                       ).sort('timestamp', pymongo.ASCENDING)))
        # set date column to datetime
        df['date'] = pd.to_datetime(df["_id"], unit='s')
        # adjust candle period 'zoom'
        if zoom:
            df.set_index('date', inplace=True)
            df = df.resample(rule=zoom,
                             closed='left',
                             label='left').apply({'open': 'first',
                                                  'high': 'max',
                                                  'low': 'min',
                                                  'close': 'last',
                                                  'quoteVolume': 'sum',
                                                  'volume': 'sum',
                                                  'weightedAverage': 'mean'})
            df.reset_index(inplace=True)
        # add indicators
        availInd = dir(indicators)
        for ind in indica:
            if ind in availInd:
                df = getattr(indicators, ind)(df, **indica[ind])
        df['percentChange'] = df['close'].pct_change().round(8) * 100
        return df

    def myTradeHistory(self, query=None):
        """
        Retrives and saves trade history in "poloniex.'self.pair'-tradeHistory"
        """
        dbcolName = self.pair + '-tradeHistory'
        db = getMongoColl('poloniex', dbcolName)
        # get last trade
        old = {'date': time() - self.api.YEAR * 10}
        try:
            old = list(db.find().sort('date', pymongo.ASCENDING))[-1]
        except:
            logger.warning('No %s trades found in database', self.pair)
        # get new data from poloniex
        hist = self.api.returnTradeHistory(self.pair, start=old['date'] - 1)

        if len(hist) > 0:
            logger.info('%d new %s trade database entries',
                        len(hist), self.pair)

            for trade in hist:
                _id = trade['globalTradeID']
                del trade['globalTradeID']
                trade['date'] = UTCstr2epoch(trade['date'])
                trade['amount'] = float(trade['amount'])
                trade['total'] = float(trade['total'])
                trade['tradeID'] = int(trade['tradeID'])
                trade['orderNumber'] = int(trade['orderNumber'])
                trade['rate'] = float(trade['rate'])
                trade['fee'] = float(trade['fee'])
                db.update_one({"_id": _id}, {"$set": trade}, upsert=True)

        return pd.DataFrame(list(db.find(query).sort('date',
                                                     pymongo.ASCENDING)))

    def myLendingHistory(self, coin=False, start=False):
        """
        Retrives and saves lendingHistory in 'poloniex.lendingHistory' database
        coin = coin to get history for (defaults to self.child)
        start = starting epoch date to get data from
        """
        if not coin:
            coin = self.child
        db = getMongoColl('poloniex', 'lendingHistory')
        # get last entry timestamp
        old = {'open': time() - self.api.YEAR * 10}
        try:
            old = list(db.find({"currency": coin}).sort('open',
                                                        pymongo.ASCENDING))[-1]
        except:
            logger.warning(RD('No %s loan history found in database!'), coin)
        # get new entries
        new = self.api.returnLendingHistory(start=old['open'] - 1)
        nLoans = [loan for loan in new if loan['currency'] == coin]
        if len(nLoans) > 0:
            logger.info(GR('%d new lending database entries'), len(new))
            for loan in nLoans:
                _id = loan['id']
                del loan['id']
                loan['close'] = UTCstr2epoch(loan['close'])
                loan['open'] = UTCstr2epoch(loan['open'])
                loan['rate'] = float(loan['rate'])
                loan['duration'] = float(loan['duration'])
                loan['interest'] = float(loan['interest'])
                loan['fee'] = float(loan['fee'])
                loan['earned'] = float(loan['earned'])
                db.update_one({'_id': _id}, {'$set': loan}, upsert=True)
        if not start:
            start = time() - self.api.DAY
        return pd.DataFrame(
            list(db.find({'currency': coin,
                          '_id': {'$gt': start}
                          }).sort('open', pymongo.ASCENDING)))

    def cancelOrders(arg=False):
        """
        Generator method that cancels all orders for self.pair. Can be
        limited to just buy or sell orders using the 'arg' param,
        yields results from 'self.api.cancelOrder'
        """
        # get open orders for 'market'
        orders = self.openOrders
        for order in orders:
            # if arg = 'sell' or 'buy' skip the orders not labeled as such
            if arg in ('sell', 'buy') and order['type'] != arg:
                continue
            # show output
            yield self.api.cancelOrder(order["orderNumber"])

    def addStopOrder(amount, stop, limit):
        self.stops.append(StopLimit(self.api, self.pair)(amount, stop, limit))

    def cancelStopOrder(indx=False):
        if indx:
            self.stops[indx].cancel()
        else:
            for stop in self.stops:
                stop.cancel()
