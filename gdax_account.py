import time
import threading

import gdax


class GDAXAccount:

	def __init__(self, api_key, api_secret_key, api_passphrase, logger):
		"""
		GDAXAccount holds information about a GDAX account like the authenticated
		client as well as how much bitcoin and dollars are in the account.
		Utilizes an account lock to prevent race conditions.

		Parameters:
			api_key: string
				32 character string representing the account's api key
			api_secret_key: string
				88 character string representing the account's api secret key
			api_passphrase: string
				11 character string representing the account's api passphrase
			logger: Log
				Used to log messages as needed.
		"""

		self.logger = logger
		self.auth_client = self.authorize_gdax_account(
			api_key, api_secret_key, api_passphrase
		)
		self.usd, self.btc = self.get_account_holdings()
		self.account_lock = threading.RLock()

	def authorize_gdax_account(
			self, api_key=None, api_secret_key=None, api_passphrase=None):
		"""
		Returns an authenticated client given valid api credentials

		Go to https://www.gdax.com/settings/api to create API credentials.
		As far as I can tell, the View, Trade and Manage permissions are necessary.
		(Not 100% sure what Manage does however.)

		Parameters:
			api_key: string
				32 character string representing the account's api key
			api_secret_key: string
				88 character string representing the account's api secret key
			api_passphrase: string
				11 character string representing the account's api passphrase

		Returns:
			authenticated_client: gdax.AuthenticatedClient
				Authenticated client that has access to GDAX account identified
				by the API key, secret key and passphrase.
		"""

		if api_key is None or api_secret_key is None or api_passphrase is None:
			raise ValueError(
				'Must input API credentials into authorize_gdax_account()'
			)

		authenticated_client = gdax.AuthenticatedClient(
			api_key, api_secret_key, api_passphrase
		)

		return authenticated_client

	def get_account_holdings(self):
		"""
		Fetches how much bitcoin and dollars the account holds.

		Returns:
			usd_holding: float
				Amount of USD in the GDAX account.
			btc_holding: float
				Amount of Bitcoin in the GDAX account.
		"""

		# JSON sometimes messes up, retry if it does
		while True:
			auth_client_accounts = self.auth_client.get_accounts()
			self.logger.add(f'auth_client_accounts: {auth_client_accounts}')
			try:
				# got a TypeError here once, message:
				# currency = account['currency'],
				# TypeError: string indices must be ints
				for account in auth_client_accounts:
					currency = account['currency']
					if currency == 'USD':
						usd_holding = float(account['balance'])
					elif currency == 'BTC':
						btc_holding = float(account['balance'])

			# Wide Exception clause because there used to be a special module
			# for handling json errors, but it's no longer always Windows
			# compatible
			except Exception as e:
				message = \
					f'Note: Exception: {e} in get_account_holdings() \n' \
					f'Retrying'
				self.logger.add(message)
				time.sleep(1)
				continue

			break

		return usd_holding, btc_holding
