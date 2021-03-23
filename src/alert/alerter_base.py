import logging

import pandas
import pymongo


logger = logging.getLogger('Alert')


class AlerterBase(object):
    FAST_FORWARD_EMOJI_UNICODE = u'\U000023E9'
    CHECK_MARK_EMOJI_UNICODE = u'\U00002705'
    FACTORY_EMOJI_UNICODE = u'\U0001F3ED'

    def __init__(self, mongo_db, telegram_bot, debug=None):
        self.name = self.__class__.__name__.lower()
        self._mongo_db = mongo_db
        self._telegram_bot = telegram_bot
        self._debug = debug

    @property
    def hierarchy(self) -> dict:
        """
        This property is a mapping between keys and a sorted list of their logical hierarchy.
        by using this mapping we could filter diffs by locating changed values in hierarchy
        """
        return {}

    @property
    def filter_keys(self):
        # List of keys to ignore
        return []

    def get_alert_msg(self, diff):
        diff = self._edit_diff(diff)

        if not diff:
            return ''

        title = '*{key}* has {verb}:'

        if diff.get('diff_type') == 'remove':
            verb = 'been removed'
            body = diff.get('old')
        elif diff.get('diff_type') == 'add':
            verb = 'been added'
            body = diff.get('new')
        else:
            verb = 'changed'
            body = '{old} {fast_forward}{fast_forward}{fast_forward} {new}'.format(
                fast_forward=self.FAST_FORWARD_EMOJI_UNICODE,
                old=diff.get('old'),
                new=diff.get('new'))

        title = title.format(key=diff.get('changed_key'), verb=verb)

        return '{title}\n' \
               '{body}'.format(title=title, body=body)

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
        key = diff.get('changed_key')

        if key is None or key == '' or key in self.filter_keys:
            return None

        elif key in self.hierarchy.keys():
            try:
                if self.hierarchy[key].index(diff['new']) < self.hierarchy[key].index(diff['old']):
                    return None

            except ValueError as e:
                logger.warning('Incorrect hierarchy for {ticker}.'.format(ticker=diff.get('ticker')))
                logger.exception(e)
        return diff

    def _get_sorted_diffs(self, ticker):
        return pandas.DataFrame(
            self._mongo_db.diffs.find({"ticker": ticker}, {"_id": False}).sort('date', pymongo.ASCENDING))
