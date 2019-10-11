import threading


class OrderTracker:

	def __init__(self):
		"""
		Simple container for data structures that map unique ids to the
		Order objects associated with that id and the corresponding locks
		to those data structures to prevent race conditions.

		There are maps by both client order id as well as order id because
		of FIX-specific terminology.

		As an example, self.orders_by_cl_oid maps a unique client order id
		to the Order object associated with that client order id.
		"""
		self.orders_by_cl_oid = {}
		self.orders_by_cl_oid_lock = threading.RLock()
		self.orders_by_oid = {}
		self.order_by_oid_lock = threading.RLock()
