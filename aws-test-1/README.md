# Sample programs

The sample programs in this folder are derived from the [AWS IoT Device SDK samples](https://github.com/aws/aws-iot-device-sdk-python-v2/tree/master/samples).
The sample command lines for each program require that the `~/certs` folder
contains these certificates for the device and account being used.

| Filename | Description |
| ----- | ----- |
| Amazon-root-CA-1.pem  | Certificate authority (CA) certificate  |
| device.pem.crt | Device (client) certificate file  |
| private.pem.key | Private key file for the device certificate |

## pi-setup.txt

Description of what you should do your Raspberry Pi after you do a clean OS
install to prepare it to run these samples.

## http-pub.py

Example of publishing an MQTT message over HTTPS.

#### Sample command line
```
python http-pub.py --topic topic_1 --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --endpoint ACCOUNT_PREFIX-ats.iot.AWS_REGION.amazonaws.com --message '{"hello": "world!"}'
```

## pubsub.py

A clone of the pubsub.py in the [AWS IoT Device SDK samples](https://github.com/aws/aws-iot-device-sdk-python-v2/tree/master/samples).
The `pubsub-led-*.py` programs are derived from this file.

## pubsub-led-1.py

First test of LED integration with sample app. Automatically sends and receives
messages and lights red LED on publish and green LED on receipt of a subscribed
message.

#### Sample command line
```
python pubsub-led-1.py --topic topic_1 --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --endpoint ACCOUNT_PREFIX-ats.iot.AWS_REGION.amazonaws.com
```

## pubsub-led-2.py

Integration of buttons to `pubsub-led-1.py`. Buttons send a message on a topic
that corresponds to the GPIO pin of the button. Lights red LED on publish and
green LED on receipt of a subscribed message.

#### Sample command line
```
python pubsub-led-2.py --topic topic_1 --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --endpoint ACCOUNT_PREFIX-ats.iot.AWS_REGION.amazonaws.com
```

## pubsub-led-3.py

Derived from `pubsub-led-2.py` to light the LED that corresponds to the button
pressed. Button press send message with topic that corresponds to GPIO of button
pressed and on receipt of the message, the corresponding LED is lit.

#### Sample command line
```
python pubsub-led-3.py --topic topic_1 --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --endpoint ACCOUNT_PREFIX-ats.iot.AWS_REGION.amazonaws.com
```

## pubsub-led-4.py

Derived from `pubsub-led-3.py` to light the LED that corresponds to the button
pressed. Button press send message with topic that corresponds to the device and
the message body contains the desired state of the LEDs after the button is
pressed. On receipt of the message, the corresponding LED is lit.

#### Sample command line
```
python pubsub-led-4.py --topic topic_1 --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --endpoint ACCOUNT_PREFIX-ats.iot.AWS_REGION.amazonaws.com
```

## shadow.py

A clone of the shadow.py in the [AWS IoT Device SDK samples](https://github.com/aws/aws-iot-device-sdk-python-v2/tree/master/samples).
The `shadow-led-*.py` programs are derived from this file.

#### Sample command line
```
python shadow-led-1.py --thing-name MyIotThing --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --endpoint ACCOUNT_PREFIX-ats.iot.AWS_REGION.amazonaws.com
```

## shadow-led-1.py

Runs in two modes: *button device* and *led device*. Button device requests the
led to light based on the last button pressed and the led device listens for
changes to the device state to light the LED that corresponds to the last button
pressed. The device state is recorded in a Device Shadow so a newly connected LED
device can display the current state of the device shadow.

#### Sample command line: button device
```
python shadow-led-1.py --thing-name MyIotThing --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --client-id buttons --endpoint ACCOUNT_PREFIX-ats.iot.AWS_REGION.amazonaws.com
```

#### Sample command line: LED device
```
python shadow-led-1.py --thing-name MyIotThing --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --client-id led-x --endpoint ACCOUNT_PREFIX-ats.iot.AWS_REGION.amazonaws.com
```

#### On device init or reconnect

1. publish_get_shadow(thing_name)  # request current shadow
  a.  on_get_shadow_accepted(response) # get shadow request was accepted
    * change_shadow_value(value)
      * updates the local shadow document
      * sets the device hardware to match the local shadow document
      * updates the shadow document on AWS
  b. on_get_shadow_rejected # no shadow exists, so create one and send it Callback
    * change_shadow_value(default_state)

#### On button press

1. btn_down(button)  # button press handler
  a. light the LED that corresponds to the button pressed
  b. update the local device state
  c. change_shadow_value(value)

#### On updated shadow received

1. on_shadow_delta_updated(delta)
   a. change_shadow_value(delta) # set the LED values to the delta msg value


## AWS IoT Learn Demo (Step 1)

Button device sends a message when a button is pressed and lights the device LEDs based on the message received. After updating the LEDs, the device sends a message reporting the current LED status.

LED device subscribes to button-pressed messages and lights the device LEDs based on the message received. After updating the LEDs, the device sends a message reporting the current LED status.


#### Command Line (button device)
```python iot-demo-step-1.py --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --client-id buttons --endpoint a2c8EXAMPLEmbb-ats.iot.us-west-2.amazonaws.com
```

#### Command Line (LED device)
```
python iot-demo-step-1.py --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --client-id leds --endpoint a2c8EXAMPLEmbb-ats.iot.us-west-2.amazonaws.com
```

### AWS IoT Learn Demo (Step 1 - with Rule)

Button device sends a message when a button is pressed and lights the device LEDs based on the message received. After updating the LEDs, the device sends a message reporting the current LED status.

Add rule in iot-demo-step-1.json and enable it.

LED device subscribes to republished messages and lights the device LEDs based on the message received. After updating the LEDs, the device sends a message reporting the current LED status.


#### Command Line (button device)
```python iot-demo-step-1.py --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --client-id buttons --endpoint a2c8EXAMPLEmbb-ats.iot.us-west-2.amazonaws.com
```

#### Command Line (LED device)
```
python iot-demo-step-1.py --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --client-id leds --led-state-topic 'demo_service/buttons/led_state/desired' --endpoint a2c8EXAMPLEmbb-ats.iot.us-west-2.amazonaws.com
```

## AWS IoT Learn Demo (Step 2)

Same as Step 1 with a rule, but the rule is different. There are two rules waiting for a message to republish. *RepublishRed* republishes a device-state message with a `Red` LED selected without changing it.  *ChangeBlueToGreen* republishes messages with `Green` and `Blue` LED requests as `Green` only.

On the button device, the LEDs will match the button pressed. On the LED device, however, both the `Green` and `Blue` buttons will light only the `Green` LED.

#### Add and enable the rules

Add the rules in iot-demo-step-2.json and enable them. Disable all other rules that use the demo message topics.

#### Command Line (button device)
```python iot-demo-step-1.py --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --client-id buttons --endpoint a2c8EXAMPLEmbb-ats.iot.us-west-2.amazonaws.com
```

#### Command Line (LED device)
```
python iot-demo-step-1.py --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --client-id leds --led-state-topic 'demo_service/buttons/led_state/desired' --endpoint a2c8EXAMPLEmbb-ats.iot.us-west-2.amazonaws.com
```

## AWS IoT Learn Demo (Step 3)

_**Coming soon**_

Same as step 2, but with an additional topic rules

## AWS IoT Learn Demo (Step 4)

Adds a device shadow to the previous steps. Adding a device shadow requires
the message logic to be redesigned to incorporate the shadow.

**iot-demo-step-4.py**

This program runs on both a button device and an led device.

#### On the button device
* Subscribe to:
  * `demo_device/buttons/led_state/pending` (led state object) to set the LEDs blinking to indicate successful receipt of button state
  * `demo_device/buttons/led_state/reported` (led state object) to set the LEDs to steady to indicate the LEDs on the LED device have been set to desired state.
  * `$aws/things/leds_demo_device/shadow/get/accepted` (get shadow) to initialize the device to match current shadow state, and then publish the reported state
  * `$aws/things/leds_demo_device/shadow/get/rejected` (get shadow) to display the error getting current shadow state.
* On btn_down:
  * Publish the button state in topic `demo_device/buttons/led_state/desired`. The message payload has the desired state of the LEDs.

#### On the led device
* subscribe to:
  * `$aws/things/leds_demo_device/shadow/get/accepted` (get shadow) to update the device to match current shadow state and then publish the reported state
  * `$aws/things/leds_demo_device/shadow/get/rejected` (get shadow) to display the error getting current shadow state
  * `$aws/things/leds_demo_device/shadow/update/delta` (shadow-delta) to update device to match desired shadow state and then publish the reported state
  * `$aws/things/leds_demo_device/shadow/update/accepted` (update shadow) confirms that the  update was successful
  * `$aws/things/leds_demo_device/shadow/update/rejected` (update shadow) confirms the update was not successful

#### The program also expects these IoT Topic Rules:
* `on_button_press`
  * **Republish** `demo_device/buttons/led_state/pending` (led state object)
* `on_button_press_shadow`
  * **Republish** `$aws/things/leds_demo_device/shadow/update` (desired state)
* `on_shadow_updated` (with reported state)
  * **Republish** `demo_device/buttons/led_state/reported` (led state object)

#### Command Line (button device)
```
python iot-demo-step-4.py --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --client-id buttons --thing-name buttons_demo_device --led-thing-name leds_demo_device --endpoint a2c8EXAMPLEmbb-ats.iot.us-west-2.amazonaws.com
```

#### Command Line (LED device)
```
python iot-demo-step-4.py --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --client-id leds --thing-name leds_demo_device --endpoint a2c8EXAMPLEmbb-ats.iot.us-west-2.amazonaws.com
```
