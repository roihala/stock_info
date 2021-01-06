import pandas
import arrow
import pymongo
import logging

from copy import deepcopy
from typing import List
from arrow import ParserError
from pymongo.database import Database
from abc import ABC, abstractmethod

from src.collect.differ import Differ


class CollectorBase(ABC):
    def __init__(self, mongo_db: Database, name, ticker, date=None, debug=False):
        """
        :param mongo_db: mongo db connection
        :param name: collection name
        :param ticker: current ticker
        :param date: date key
        :param debug: is debug?
        """
        self.ticker = ticker.upper()
        self.name = name
        self.collection = mongo_db.get_collection(self.name)
        self._mongo_db = mongo_db
        self._sorted_history = self.get_sorted_history(apply_filters=False)
        self._latest = self.get_latest()
        self._date = date if date else arrow.utcnow()
        self._current_data = None
        self._debug = debug

    @abstractmethod
    def fetch_data(self) -> dict:
        pass

    @property
    def hierarchy(self) -> dict:
        """
        This property is a mapping between keys and a sorted list of their logical hierarchy.
        by using this mapping we could filter diffs by locating changed values in hierarchy
        """
        return {}

    @property
    def nested_keys(self) -> dict:
        """
        This property is a mapping between nested keys and a sorted list of layers which will be provided to differ
        in order to get changes from the last layer only
        """
        return {}

    @property
    def filter_keys(self):
        # List of keys to ignore
        return []

    def collect(self):
        self._current_data = self.fetch_data()

        # Updating DB with the new data
        copy = deepcopy(self._current_data)
        copy.update({"ticker": self.ticker, "date": self._date.format()})

        if self._debug:
            logging.info('{name} fetched data: {data}'.format(name=self.name, data=self._current_data))

        return copy

    def get_sorted_history(self, apply_filters=True):
        history = pandas.DataFrame(
            self.collection.find({"ticker": self.ticker}, {"_id": False}).sort('date', pymongo.ASCENDING))

        if apply_filters:
            try:
                return self.__apply_filters(history)

            except Exception as e:
                logging.exception(e)
                return history

        return history

    def __apply_filters(self, history):
        # Filtering all consecutive row duplicates where every column has the same value
        cols = history.columns.difference(['date', 'verifiedDate'])
        history = history.loc[(history[cols].shift() != history[cols]).any(axis='columns')]

        # Handling unhashable types
        for index, col in history.applymap(lambda x: isinstance(x, dict) or isinstance(x, list)).all().items():
            if col:
                history[index] = history[index].astype('str').value_counts()

        # Dropping monogemic columns where every row has the same value
        nunique = history.apply(pandas.Series.nunique)
        cols_to_drop = nunique[nunique == 1].index

        return history.drop(cols_to_drop, axis=1).dropna(axis='columns')

    def get_latest(self):
        if self._sorted_history.empty:
            return None

        # to_dict indexes by rows, therefore getting the highest index
        history_as_dicts = self._sorted_history.tail(1).drop(['date', 'ticker'], 'columns').to_dict('index')
        return history_as_dicts[max(history_as_dicts.keys())]

    def get_diffs(self) -> List[dict]:
        """
        This function returns the changes that occurred in a ticker's data.

        :return: A dict in the format of:
        {
            "ticker": The ticker,
            "date": The current date,
            "changed_key": The key that have changed
            "old": The "old" value,
            "new": The "new" value,
            "diff_type": The type of the diff, could be add, remove, etc...
            "source": Which collection did it come from?
        }

        """
        if self._current_data is None:
            raise Exception('You should use collect() before using get_diffs()')

        if self._latest is None:
            return []

        try:

            diffs = Differ().get_diffs(self._latest, self._current_data, self.nested_keys)
            diffs = [self.__decorate_diff(diff) for diff in diffs]

            # Applying filters
            return self._edit_diffs(diffs)
        except Exception as e:
            logging.warning('Failed to get diffs between:\n{latest}\n>>>>>>\n{current}'.format(latest=self._latest,
                                                                                               current=self._current_data))
            logging.exception(e)

    def _edit_diffs(self, diffs) -> List[dict]:
        """
        This function is for editing the list of diffs right before they are alerted
        The diffs will have the following structure:

        {
            "ticker": The ticker,
            "date": The current date,
            "changed_key": The key that have changed
            "old": The "old" value,
            "new": The "new" value,
            "diff_type": The type of the diff, could be add, remove, etc...
            "source": Which collection did it come from?
        }
        """
        edited_diffs = []

        for diff in diffs:
            diff = self._edit_diff(diff)
            
            if diff is not None and diff['changed_key'] not in self.filter_keys:
                edited_diffs.append(diff)

        return edited_diffs

    def _edit_diff(self, diff) -> dict:
        """
        This function is for editing or deleting an existing diff.
        It will be called with every diff that has been found while maintaining the diff structure of:

        {
            "ticker": The ticker,
            "date": The current date,
            "changed_key": The key that have changed
            "old": The "old" value,
            "new": The "new" value,
            "diff_type": The type of the diff, could be add, remove, etc...
            "source": Which collection did it come from?
        }

        :return: The edited diff, None to delete the diff
        """
        key = diff['changed_key']

        if key == '':
            return None
        elif key in self.hierarchy.keys():
            try:
                if self.hierarchy[key].index(diff['new']) < self.hierarchy[key].index(diff['old']):
                    return None
            # If the key is not in hierarchy list
            except ValueError as e:
                logging.warning('Incorrect hierarchy for {ticker}. {error}'.format(ticker=self.ticker, error=e.args))
        return diff

    def __decorate_diff(self, diff):
        # joining by '.' if a key is a list of keys (differ's nested changes approach)
        key = diff['changed_key'] if not isinstance(diff['changed_key'], list) else \
            '.'.join((str(part) for part in diff['changed_key']))

        diff.update({
            "ticker": self.ticker,
            "date": self._date.format(),
            "changed_key": key,
            "source": self.name
        })
        return diff

    @staticmethod
    def timestamp_to_datestring(value):
        try:
            return arrow.get(value).format()
        except (ParserError, TypeError, ValueError):
            return value
