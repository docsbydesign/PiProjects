from gpiozero import LED, Button
from signal import pause

red_led = LED(16)
grn_led = LED(20)
blu_led = LED(21)

red_btn = Button(5)
grn_btn = Button(6)
blu_btn = Button(13)

red_led.off()
grn_led.off()
blu_led.off()

red_btn.when_pressed  = red_led.toggle

grn_btn.when_pressed  = grn_led.toggle

blu_btn.when_pressed  = blu_led.toggle

pause()
