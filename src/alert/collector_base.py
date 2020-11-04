import pandas
import arrow
import pymongo
import logging

from dictdiffer import diff as differ
from copy import deepcopy
from typing import List
from arrow import ParserError
from pymongo.database import Database
from abc import ABC, abstractmethod


class CollectorBase(ABC):
    def __init__(self, mongo_db: Database, name, ticker, date=None, debug=False):
        self.ticker = ticker.upper()
        self.name = name
        self.collection = mongo_db.get_collection(self.name)
        self._mongo_db = mongo_db
        self._sorted_history = self.get_sorted_history()
        self._latest = self.__get_latest()
        self._date = date if date else arrow.utcnow()
        self._current_data = None
        self._debug = debug

    @abstractmethod
    def fetch_data(self) -> dict:
        pass

    @abstractmethod
    def _filter_diff(self, diff) -> bool:
        pass

    def collect(self):
        self._current_data = self.fetch_data()

        # Updating DB with the new data
        entry = deepcopy(self._current_data)
        entry.update({"ticker": self.ticker, "date": self._date.format()})
        if not self._debug:
            self.collection.insert_one(entry)
        else:
            logging.info('collection.insert_one: {entry}'.format(entry=entry))

    def get_sorted_history(self, duplicates=False):
        history = pandas.DataFrame(
            self.collection.find({"ticker": self.ticker}, {"_id": False}).sort('date', pymongo.ASCENDING))
        if duplicates:
            return history
        else:
            # Filtering all consecutive duplicates
            cols = history.columns.difference(['date', 'verifiedDate'])
            return history.loc[(history[cols].shift() != history[cols]).any(axis='columns')]

    def get_diffs(self) -> List[dict]:
        """
        This function returns the changes that occurred in a ticker's data.

        :return: A dict in the format of:
        {
            "ticker": The ticker,
            "date": The current date,
            "changed_key": The key that have changed
            "old": The "old" value,
            "new": The "new" value
        }

        """
        if self._current_data is None:
            raise Exception('You should use collect() before using get_changes()')

        if self._latest is None:
            return []

        diffs = self.__parse_diffs(differ(self._latest, self._current_data))

        # Applying filters
        return list(filter(self._filter_diff, diffs))

    def __parse_diffs(self, diffs):
        parsed_diffs = []

        for diff_type, key, values in diffs:
            if diff_type == 'change':
                # The first value is old, the second is new
                parsed_diffs.append(self.__build_diff(values[0], values[1], key, diff_type))
            elif diff_type == 'remove':
                # The removed value is in the list where the first cell is the index - therefore taking the "1" = value.
                parsed_diffs.append(self.__build_diff(values[0][1], None, key, diff_type))
            elif diff_type == 'add':
                # The removed value is in the list where the first cell is the index - therefore taking the "1" = value.
                parsed_diffs.append(self.__build_diff(None, values[0][1], key, diff_type))

        return parsed_diffs

    def __build_diff(self, old, new, key, diff_type):
        key = key if not isinstance(key, list) else '.'.join((str(part) for part in key))
        return {
            "ticker": self.ticker,
            "date": self._date.format(),
            "changed_key": key,
            "old": old,
            "new": new,
            "diff_type": diff_type
        }

    def __get_latest(self):
        if self._sorted_history.empty:
            return None

        # to_dict indexes by rows, therefore getting the highest index
        history_dict = self._sorted_history.tail(1).drop(['date', 'ticker'], 'columns').to_dict('index')
        return history_dict[max(history_dict.keys())]

    @staticmethod
    def timestamp_to_datestring(value):
        try:
            return arrow.get(value).format()
        except (ParserError, TypeError):
            return value
