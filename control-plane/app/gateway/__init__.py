"""Gateway: the live link between ZipZy and the connectors running in customers' networks.

Connectors dial OUT to /v1/connectors/stream (WebSocket). Nothing ever connects into a
customer's network. See protocol.py for the messages and hub.py for request routing.
"""
