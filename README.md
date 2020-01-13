# Cryptobot

Cryptobot is a multithreaded application that uses WebSockets and FIX protocol to trade crypto on gdax (now Coinbase Pro).

<p align="center">
  <img src="https://github.com/arda-arslan/cryptobot/blob/master/assets/cryptobot_img.png" width="95%" />
</p>

## Description

This program was written to explore the world of high-frequency trading with cryptocurrency rather than to apply a rigorous trading strategy so it isn't necessarily profitable. A simple market making approach is implemented where the bot enters on the side of the order book with the most volume at the most competitive bid and ask prices and it exits on the other side, capturing the spread. There are two reasons the bot enters on the side with the most volume:
1. If the opposite was done, it could be easy for the bot to enter a position where the market keeps moving against it and it can't get out of it's position.
2. This methodology is very straightforward which makes it easier to take the focus off of the trading strategy and put more effort on the technical problems of managing the order book, managing orders, etc.

There was a lot to learn so the code in this bot was iterated on very quickly so that it would run without errors. There are better ways to implement this program (like using min and max heaps to keep track of the most competitive bid and ask prices, for example) and some of the notable shortcomings are labeled with a TODO.

## Quick Setup

1. Enter account details in `src/main.py`
```
# Account information
api_key = 'your_api_key'
api_secret_key = 'your_api_secret_key'
api_passphrase = 'your_api_passphrase'
```
2. Setup [stunnel](https://www.stunnel.org/howto.html)

## Requirements
- Python 3.6
- gdax v1.06
- numpy
- websocket v0.40.0

## TODO
- [x] Transition from REST to FIX & WebSockets
- [x] Cover most frequently used FIX messages
- [ ] Move account details from source code to a file on .gitignore
- [ ] Create wrapper around objects that use locks so that they implicitly lock on calls
- [ ] Only run `strategy_manger()` on order book updates
- [ ] Change order book data structure from array to heap
