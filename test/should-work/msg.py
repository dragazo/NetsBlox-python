#!/usr/bin/env python

import netsblox
import time

client = netsblox.Client()

total_a,total_b = 0,0

def foo(ticks):
    global total_a
    total_a += ticks
def bar(ticks):
    global total_b
    total_b += ticks
client.on_message('tick', foo)
client.on_message('tick', bar)

for i in range(1,11):
    client.send_message('tick', ticks = i)
    time.sleep(0.5)
assert total_a == 55
assert total_b == 55
