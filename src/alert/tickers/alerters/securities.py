from src.alert.tickers.ticker_alerter import TickerAlerter


class Securities(TickerAlerter):
    @staticmethod
    def get_keys_translation():
        return {"tierDisplayName": "Tier",
                "tierCode": "Tier",
                "authorizedShares": "Authorized Shares",
                "outstandingShares": "Outstanding Shares",
                "transferAgents": "Transfer Agents",
                "restrictedShares": "Restricted Shares",
                "unrestrictedShares": "Unrestricted Shares"}

    @property
    def relevant_keys(self):
        return ['transferAgents', 'tierCode']

    @property
    def extended_keys(self):
        return ['authorizedShares', 'outstandingShares', 'restrictedShares', 'unrestrictedShares']

    @staticmethod
    def get_hierarchy() -> dict:
        return {
            'tierDisplayName': ['Expert Market', 'Grey Market', 'Pink No Information', 'Pink Limited Information', 'Pink Current Information', 'OTCQB',
                                'OTCQX International'],
            'tierCode': ['GM', 'EM', 'PN', 'PL', 'PC', 'QB']
        }

    @staticmethod
    def get_tier_translation(key=None):
        tier_translation = {
            'QB': 'OTCQB',
            'PC': 'Pink Current Information',
            'PL': 'Pink Limited Information',
            'PN': 'Pink No Information',
            'EM': 'Expert Market',
            'GM': 'Grey Market'
        }

        if key:
            return tier_translation.get(key)
        else:
            return tier_translation

    def is_relevant_diff(self, diff):
        if diff.get('changed_key') in self.extended_keys and type(diff.get('new')) is int:
            if not diff.get('old') or self.calc_ratio(diff) < -0.2:
                return True
        return super().is_relevant_diff(diff)

    def edit_diff(self, diff):
        old, new = diff['old'], diff['new']

        diff = super().edit_diff(diff)

        if isinstance(new, int):
            try:
                int(old)
            except ValueError:
                old = 0

        if isinstance(new, int):
            ratio = self.calc_ratio(diff)
            old, new = f'{old:,}', f'{new:,}'

            if diff.get('changed_key') in self.extended_keys:
                new = new + " ({:.0%})".format(ratio) if ratio else new

        elif diff['changed_key'] == 'tierCode':
            old, new = self.get_tier_translation(old), self.get_tier_translation(new)

        diff['old'], diff['new'] = old, new

        return diff

    @staticmethod
    def calc_ratio(diff):
        try:
            return (int(diff.get('new')) - int(diff.get('old'))) / int(diff.get('old'))
        except ValueError:
            return 0
