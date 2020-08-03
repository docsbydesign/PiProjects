# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.

from __future__ import absolute_import
from __future__ import print_function
import argparse
from awscrt import io, mqtt, auth, http
from awsiot import mqtt_connection_builder
import sys
import threading
import time
from uuid import uuid4
from gpiozero import LED, Button
from signal import pause
import json

# This sample uses the Message Broker for AWS IoT to send and receive messages
# through an MQTT connection. On startup, the device connects to the server,
# subscribes to a topic, and begins publishing messages to that topic.
# The device should receive those same messages back from the message broker,
# since it is subscribed to that same topic.

parser = argparse.ArgumentParser(description="Send and receive messages through and MQTT connection.")
parser.add_argument('--endpoint', required=True, help="Your AWS IoT custom endpoint, not including a port. " +
                                                      "Ex: \"abcd123456wxyz-ats.iot.us-east-1.amazonaws.com\"")
parser.add_argument('--cert', help="File path to your client certificate, in PEM format.")
parser.add_argument('--key', help="File path to your private key, in PEM format.")
parser.add_argument('--root-ca', help="File path to root certificate authority, in PEM format. " +
                                      "Necessary if MQTT server uses a certificate that's not already in " +
                                      "your trust store.")
parser.add_argument('--client-id', default="test-" + str(uuid4()), help="Client ID for MQTT connection.")
parser.add_argument('--topic', default="test/topic", help="Topic to subscribe to, and publish messages to.")
parser.add_argument('--message', default="Hello World!", help="Message to publish. " +
                                                              "Specify empty string to publish nothing.")
parser.add_argument('--count', default=0, type=int, help="Number of messages to publish/receive before exiting. " +
                                                          "Default is 0 to run forever.")
parser.add_argument('--use-websocket', default=False, action='store_true',
    help="To use a websocket instead of raw mqtt. If you " +
    "specify this option you must specify a region for signing, you can also enable proxy mode.")
parser.add_argument('--signing-region', default='us-east-1', help="If you specify --use-web-socket, this " +
    "is the region that will be used for computing the Sigv4 signature")
parser.add_argument('--proxy-host', help="Hostname for proxy to connect to. Note: if you use this feature, " +
    "you will likely need to set --root-ca to the ca for your proxy.")
parser.add_argument('--proxy-port', type=int, default=8080, help="Port for proxy to connect to.")
parser.add_argument('--verbosity', choices=[x.name for x in io.LogLevel], default=io.LogLevel.NoLogs.name,
    help='Logging level')

# LED states
LED_LIT = True
LED_OFF = False
LED_STATES = [LED_OFF, LED_LIT]
LED_COLORS = ["Red","Green","Blue"]
GPIO_LED_PINS = [16,20,21]
GPIO_BTN_PINS = [5,6,13]

# Using globals to simplify sample code
args = parser.parse_args()

io.init_logging(getattr(io.LogLevel, args.verbosity), 'stderr')

received_count = 0
received_all_event = threading.Event()

def create_led (gpio_led_pin, gpio_btn_name, color, initial_state = LED_OFF):
    if gpio_led_pin not in GPIO_LED_PINS:
        return None
    if color not in LED_COLORS:
        return None
    if initial_state not in LED_STATES:
        initial_state = LED_OFF
    # create LED object
    led_object = LED(gpio_led_pin, True, initial_state)
    # initialize the dictionary for this LED
    new_led = {
        "led_pin": gpio_led_pin,
        "led_name": str(led_object.pin),
        "btn_name": gpio_btn_name,
        "color": color,
        "state": led_object.value,
        "led": led_object
    }
    return new_led

def set_led(btn_name):
    global device_leds
    for d_led in device_leds:
        if d_led["btn_name"] == btn_name:
            d_led["led"].value = True
            d_led["state"] = d_led["led"].value
        else
            # turn off all other LEDs
            d_led["led"].value = False
            d_led["state"] = d_led["led"].value
    return None


def update_device_state():
    global device_state
    device_state["Red"] = device_leds["Red"]["state"]
    device_state["Green"] = device_leds["Green"]["state"]
    device_state["Blue"] = device_leds["Blue"]["state"]
    return True


# Callback when connection is accidentally lost.
def on_connection_interrupted(connection, error, **kwargs):
    print("Connection interrupted. error: {}".format(error))


# Callback when an interrupted connection is re-established.
def on_connection_resumed(connection, return_code, session_present, **kwargs):
    print("Connection resumed. return_code: {} session_present: {}".format(return_code, session_present))

    if return_code == mqtt.ConnectReturnCode.ACCEPTED and not session_present:
        print("Session did not persist. Resubscribing to existing topics...")
        resubscribe_future, _ = connection.resubscribe_existing_topics()

        # Cannot synchronously wait for resubscribe result because we're on the connection's event-loop thread,
        # evaluate result with a callback instead.
        resubscribe_future.add_done_callback(on_resubscribe_complete)


def on_resubscribe_complete(resubscribe_future):
        resubscribe_results = resubscribe_future.result()
        print("Resubscribe results: {}".format(resubscribe_results))

        for topic, qos in resubscribe_results['topics']:
            if qos is None:
                sys.exit("Server rejected resubscribe to topic: {}".format(topic))


def subscribe_to_local_topic(args, local_topic):
    # Subscribe
    sub_topic = "{}/{}".format(args.topic,local_topic)
    #print("Subscribing to topic '{}'...".format(args.topic))
    print("Subscribing to topic '{}'...".format(sub_topic))
    subscribe_future, packet_id = mqtt_connection.subscribe(
        topic=sub_topic,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=on_message_received)
    subscribe_result = subscribe_future.result()
    print("Subscribed with {}".format(str(subscribe_result['qos'])))


# Callback when the subscribed topic receives a message
def on_message_received(topic, payload, **kwargs):
    print("Received message from topic '{}': {}".format(topic, payload))
    global received_count
    global device_leds

    # get the button ID from the topic
    topic_elems = split(topic,"/")
    topic_btn = topic_elems[len(topic_elems)-1] # last element in topic
    # read the message to get the current button state
    payload_data = json.loads(payload)
    # set the corresponding led to the current state
    if payload_data["button_pressed"]:
        set_led(topic_btn)

    if received_count == args.count:
        received_all_event.set()

def btn_down (button):
    button_state = {"button_pressed" : True}
    message = json.dumps(button_state)
    publish_message (button, message)

def publish_message (button, message):
    # this is the button press handler
    #   the GPIO library send this handler the button object
    #   of the button that fired it off.
    #   https://gpiozero.readthedocs.io/en/stable/api_input.html#button
    global args
    global mqtt_connection
    global publish_count

    print("Publishing message to topic '{}': {}".format(args.topic, message))
    msg_topic=args.topic + "/" + str(button.pin)
    mqtt_connection.publish(
        topic=msg_topic,
        payload=message,
        qos=mqtt.QoS.AT_LEAST_ONCE)
    publish_count += 1


if __name__ == '__main__':

    # Spin up resources
    event_loop_group = io.EventLoopGroup(1)
    host_resolver = io.DefaultHostResolver(event_loop_group)
    client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)

    #initialize buttons
    red_btn = Button(5, bounce_time=0.1)
    grn_btn = Button(6, bounce_time=0.1)
    blu_btn = Button(13, bounce_time=0.1)

    # intialize LEDs and set to off (the default)
    device_leds = {
        "Red": create_led(16, str(red_btn.pin), "Red"),
        "Green": create_led(20, str(grn_btn.pin), "Green"),
        "Blue": create_led(21, str(blu_btn.pin), "Blue")
    }
    # initialize device state
    device_state = {
        "Red": device_leds["Red"]["state"],
        "Green": device_leds["Green"]["state"],
        "Blue": device_leds["Blue"]["state"]
    }

    if args.use_websocket == True:
        proxy_options = None
        if (args.proxy_host):
            proxy_options = http.HttpProxyOptions(host_name=args.proxy_host, port=args.proxy_port)

        credentials_provider = auth.AwsCredentialsProvider.new_default_chain(client_bootstrap)
        mqtt_connection = mqtt_connection_builder.websockets_with_default_aws_signing(
            endpoint=args.endpoint,
            client_bootstrap=client_bootstrap,
            region=args.signing_region,
            credentials_provider=credentials_provider,
            websocket_proxy_options=proxy_options,
            ca_filepath=args.root_ca,
            on_connection_interrupted=on_connection_interrupted,
            on_connection_resumed=on_connection_resumed,
            client_id=args.client_id,
            clean_session=False,
            keep_alive_secs=6)

    else:
        mqtt_connection = mqtt_connection_builder.mtls_from_path(
            endpoint=args.endpoint,
            cert_filepath=args.cert,
            pri_key_filepath=args.key,
            client_bootstrap=client_bootstrap,
            ca_filepath=args.root_ca,
            on_connection_interrupted=on_connection_interrupted,
            on_connection_resumed=on_connection_resumed,
            client_id=args.client_id,
            clean_session=False,
            keep_alive_secs=6)

    print("Connecting to {} with client ID '{}'...".format(
        args.endpoint, args.client_id))

    connect_future = mqtt_connection.connect()

    # Future.result() waits until a result is available
    connect_future.result()
    print("Connected!")

    # Subscribe to all the button messages
    subscribe_to_local_topic(args, str(red_btn.pin))
    subscribe_to_local_topic(args, str(grn_btn.pin))
    subscribe_to_local_topic(args, str(blu_btn.pin))

    # Publish message to server desired number of times.
    # This step is skipped if message is blank.
    # This step loops forever if count was set to 0.
    if args.message:
        if args.count == 0:
            print ("Sending messages until program killed")
        else:
            print ("Sending {} message(s)".format(args.count))

        # assign button press handlers
        red_btn.when_pressed = btn_down
        grn_btn.when_pressed = btn_down
        blu_btn.when_pressed = btn_down

        # loop to check publish count progress
        publish_count = 1
        while (publish_count <= args.count) or (args.count == 0):
            # the publish count should update asynchronously while sleeping.
            time.sleep(2)

    # Wait for all messages to be received.
    # This waits forever if count was set to 0.
    if args.count != 0 and not received_all_event.is_set():
        print("Waiting for all messages to be received...")

    received_all_event.wait()
    print("{} message(s) received.".format(received_count))

    # Disconnect
    print("Disconnecting...")
    disconnect_future = mqtt_connection.disconnect()
    disconnect_future.result()
    print("Disconnected!")
