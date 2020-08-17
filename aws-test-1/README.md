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
