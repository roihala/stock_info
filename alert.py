import datetime
from functools import reduce

import telegram
from time import sleep

from pymongo.change_stream import CollectionChangeStream

from scheduler_utils import disable_apscheduler_logs
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

from runnable import Runnable
from src.factory import Factory


class Alert(Runnable):
    def __init__(self):
        super().__init__()

        self._scheduler = BackgroundScheduler(executors={
            'default': ThreadPoolExecutor(10),
        }, timezone="Africa/Abidjan")

        disable_apscheduler_logs()

        self._scheduler.start()

    def run(self):
        self.listen()

    def listen(self):
        while True:
            try:
                with self._mongo_db.diffs.watch() as stream:
                    event = stream.next()

                    alerts = {diff.pop('_id'): self.__get_alert(diff) for diff in self.__get_diffs(stream, event)}

                    if alerts:
                        self.__send_or_delay(reduce(lambda x, y: x + '\n' + y, alerts.values()))
                        [self._mongo_db.diffs.update_one({'_id': object_id}, {'$set': {"alerted": True}}) for object_id in alerts.keys()]

            except Exception as e:
                # We know it's unrecoverable:
                self.logger.exception(e)

            sleep(5)

    def __get_diffs(self, stream: CollectionChangeStream, first_event) -> list:
        event = first_event
        diffs = []

        while event is not None:
            self.logger.info('event: {event}'.format(event=event))

            diff = event['fullDocument']

            if event['operationType'] == 'insert' and diff.get('source') not in self.get_daily_alerters():
                diffs.append(diff)

            event = stream.try_next()

        return diffs

    def __get_alert(self, diff):
        try:
            alerter_args = {'mongo_db': self._mongo_db, 'telegram_bot': self._telegram_bot,
                            'debug': self._debug}
            alerter = Factory.alerters_factory(diff.get('source'), **alerter_args)

            return alerter.get_alert_msg(diff)

        except Exception as e:
            self.logger.warning("Couldn't create alerter for {diff}".format(diff=diff))
            self.logger.exception(e)

    def __send_or_delay(self, msg):
        self.__send_msg(self._mongo_db.telegram_users.find({'delay': False}), msg)
        self.__send_delayed(self._mongo_db.telegram_users.find({'delay': True}), msg)

    def __send_delayed(self, delayed_users, msg):
        trigger = DateTrigger(run_date=datetime.datetime.utcnow() + datetime.timedelta(minutes=10))

        self._scheduler.add_job(self.__send_msg,
                                args=[delayed_users, msg],
                                trigger=trigger)

    def __send_msg(self, users_group, msg):
        for user in users_group:
            try:
                self._telegram_bot.sendMessage(chat_id=user.get("chat_id"), text=msg,
                                               parse_mode=telegram.ParseMode.MARKDOWN)

            except Exception as e:
                self.logger.exception(e)

    @staticmethod
    def get_daily_alerters():
        return ['securities']


if __name__ == '__main__':
    Alert().run()
