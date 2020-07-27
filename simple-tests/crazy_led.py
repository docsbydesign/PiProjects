from gpiozero import LED, Button
from signal import pause
from time import sleep
from random import randint

red = 0
grn = 1
blu = 2
first_led = red
last_led = blu

red_led = LED(16)
grn_led = LED(20)
blu_led = LED(21)

leds = [red_led, grn_led, blu_led]

red_btn = Button(5)
grn_btn = Button(6)
blu_btn = Button(13)

red_led.off()
grn_led.off()
blu_led.off()

while True:
    red_btn.when_pressed  = leds[randint(first_led, last_led)].toggle
    grn_btn.when_pressed  = leds[randint(first_led, last_led)].toggle
    blu_btn.when_pressed  = leds[randint(first_led, last_led)].toggle
    sleep(3)

pause()
