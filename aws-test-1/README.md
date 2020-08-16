# Sample programs

The sample programs in this folder are derived from the [AWS IoT Device SDK samples](https://github.com/aws/aws-iot-device-sdk-python-v2/tree/master/samples).

## pi-setup.txt

Description of what you should do after a clean OS install to prepare the
system for these samples.

## http-pub.py

Example of sending an MQTT message over HTTPS.

## pubsub.py

A clone of the pubsub.py in the [AWS IoT Device SDK samples](https://github.com/aws/aws-iot-device-sdk-python-v2/tree/master/samples).
The `pubsub-led-*.py` programs are derived from this file.

## pubsub-led-1.py

First test of LED integration with sample app. Automatically sends and receives
messages and lights red LED on publish and green LED on receipt of a subscribed
message.

### Sample command line
```
python pubsub-led-1.py --topic topic_1 --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --endpoint ACCOUNT_PREFIX-ats.iot.us-west-2.amazonaws.com
```

## pubsub-led-2.py

Integration of buttons to `pubsub-led-1.py`. Buttons send a message on a topic
that corresponds to the GPIO pin of the button. Lights red LED on publish and
green LED on receipt of a subscribed message.

### Sample command line
```
python pubsub-led-2.py --topic topic_1 --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --endpoint ACCOUNT_PREFIX-ats.iot.AWS_REGION.amazonaws.com
```

## pubsub-led-3.py

Derived from `pubsub-led-2.py` to light the LED that corresponds to the button
pressed. Button press send message with topic that corresponds to GPIO of button
pressed and on receipt of the message, the corresponding LED is lit.

### Sample command line
```
python pubsub-led-3.py --topic topic_1 --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --endpoint ACCOUNT_PREFIX-ats.iot.AWS_REGION.amazonaws.com
```

## pubsub-led-4.py

Derived from `pubsub-led-3.py` to light the LED that corresponds to the button
pressed. Button press send message with topic that corresponds to the device and
the message body contains the desired state of the LEDs after the button is
pressed. On receipt of the message, the corresponding LED is lit.

### Sample command line
```
python pubsub-led-4.py --topic topic_1 --root-ca ~/certs/Amazon-root-CA-1.pem --cert ~/certs/device.pem.crt --key ~/certs/private.pem.key --endpoint ACCOUNT_PREFIX-ats.iot.AWS_REGION.amazonaws.com
```
