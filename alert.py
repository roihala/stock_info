#!/usr/bin/env python3
import argparse
import logging
import os
import arrow
import pymongo
import pandas
import telegram
from pymongo import MongoClient

from src.alert.collector_base import CollectorBase
from src.alert.collectors.profile import Profile
from src.alert.collectors.symbols import Symbols
from src.find.site import InvalidTickerExcpetion

LOGGER_PATH = os.path.join(os.path.dirname(__file__), 'alert.log')
DEFAULT_CSV_PATH = os.path.join(os.path.dirname(__file__), 'tickers.csv')


class Alert(object):
    ALERT_EMOJI_UNICODE = u'\U0001F6A8'
    COLLECTORS = {'symbols': Symbols,
                  'profile': Profile}

    def __init__(self, args):
        logging.basicConfig(filename=LOGGER_PATH, level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

        self._mongo_db = self.init_mongo(args.uri)
        self._tickers_list = self.extract_tickers(args)
        self._telegram_bot = self.init_telegram(args.token)
        self._debug = args.debug

    @staticmethod
    def init_mongo(mongo_uri):
        try:
            # Using selection timeout in order to check connectivity
            mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=1)

            # Forcing a connection to mongo
            mongo_client.server_info()

            return mongo_client.stocker

        except pymongo.errors.ServerSelectionTimeoutError:
            raise ValueError("Couldn't connect to MongoDB, check your credentials")

    @staticmethod
    def extract_tickers(args):
        try:
            if args.csv:
                file_path = args.csv
            else:
                file_path = DEFAULT_CSV_PATH

            df = pandas.read_csv(file_path)
            return df.Symbol.apply(lambda ticker: ticker.upper())
        except Exception:
            raise ValueError('Invalid csv file - validate the path and that the tickers are under a column named symbol')

    @staticmethod
    def init_telegram(token):
        try:
            return telegram.Bot(token)
        except telegram.error.Unauthorized:
            raise ValueError("Couldn't connect to telegram, check your credentials")

    def collect_all(self):
        for name, obj in self.COLLECTORS.items():
            self.collect(obj, name)

    def collect(self, collector_obj, collection):
        for ticker in self._tickers_list:
            try:
                # Using date as a key for matching entries between collections
                date = arrow.utcnow()
                logging.info(' running on {collection}, {ticker}'.format(ticker=ticker, collection=collection))

                collector = collector_obj(self._mongo_db, collection, ticker, date, self._debug)

                collector.collect()

                diffs = collector.get_diffs()
                logging.info('changes: {changes}'.format(changes=diffs))

                if diffs:

                    # Insert the new diffs to mongo
                    [self._mongo_db.diffs.insert_one(diff) for diff in diffs]

                    # Alert every registered user
                    [self.__telegram_alert(diff) for diff in diffs]

            except InvalidTickerExcpetion:
                logging.warning('Suspecting invalid ticker {ticker}'.format(ticker=ticker))
            except pymongo.errors.OperationFailure as e:
                raise Exception("Mongo connectivity problems, check your credentials. error: {e}".format(e=e))
            except Exception as e:
                logging.warning('Exception on {ticker}: {e}'.format(ticker=ticker, e=e))

    def __telegram_alert(self, change):
        # User-friendly message
        msg = self.ALERT_EMOJI_UNICODE + ' Detected change on {ticker}:\n*{key}* has changed from {old} to {new}'.format(
            ticker=change.get('ticker'), key=change.get('changed_key'), old=change.get('old'), new=change.get('new'))

        for user in self._mongo_db.telegram_users.find():
            try:
                self._telegram_bot.sendMessage(chat_id=user.get("chat_id"), text=msg, parse_mode=telegram.ParseMode.MARKDOWN)

            except telegram.error.BadRequest:
                logging.warning("Can't alert to {user} - invalid chat id: {chat_id}".format(
                    user=user.get('user_name'), chat_id=user.get('chat_id')))


def main():
    Alert(get_args()).collect_all()


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', dest='csv', help='path to csv tickers file')
    parser.add_argument('--debug', dest='debug', help='debug_mode', default=False, action='store_true')
    parser.add_argument('--uri', dest='uri', help='MongoDB URI of the format mongodb://...', required=True)
    parser.add_argument('--token', dest='token', help='Telegram bot token', required=True)

    return parser.parse_args()


if __name__ == '__main__':
    main()
