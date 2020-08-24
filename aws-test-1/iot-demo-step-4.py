# Adapted from https://github.com/aws/aws-iot-device-sdk-python-v2/blob/master/samples/pubsub.py
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.

from __future__ import absolute_import
from __future__ import print_function
import argparse
from awscrt import io, mqtt, auth, http
from awsiot import mqtt_connection_builder
import traceback
import sys
import threading
from uuid import uuid4
from gpiozero import LED, Button
import json

# This sample uses the Message Broker for AWS IoT to send and receive messages
# through an MQTT connection to emulate Step 4 of the learning demo at
# https://console.aws.amazon.com/iot/home#/tutorial-intro.
#
# On startup, the button device connects to the server, subscribes to its
#  device shadow topics and then get's the current device shaodw value.
#  If no device shadow exists, it creates an empty one.
# When a button is pressed, the device publishes a desired LED state to
#  its device shadow, which then publishes a delta message indicating that
#  the requested state no longer matches the current state.
# Devices with LEDs (the button and the LED device) subscribe to the delta
#  The button device confirms that the device state has been updated to match
#  the shadow device.

DEFAULT_BUTTON_DEVICE_LED_TOPIC_DESIRED = "demo_device/buttons/led_state/desired"

parser = argparse.ArgumentParser(description="Use MQTT messages to emulate Step 1 of the AWS IoT learning demo.")
parser.add_argument('--endpoint', required=True, help="Your AWS IoT custom endpoint, not including a port. " +
                                                      "Ex: \"abcd123456wxyz-ats.iot.us-east-1.amazonaws.com\"")
parser.add_argument('--cert', help="File path to your client certificate, in PEM format.")
parser.add_argument('--key', help="File path to your private key, in PEM format.")
parser.add_argument('--root-ca', help="File path to root certificate authority, in PEM format. " +
                                      "Necessary if MQTT server uses a certificate that's not already in " +
                                      "your trust store.")
parser.add_argument('--thing-name', required=True, help="The name assigned to your IoT Thing")
parser.add_argument('--client-id', default="test-" + str(uuid4()), help="Client ID of this device for MQTT connection.")
parser.add_argument('--led-state-topic', default=DEFAULT_BUTTON_DEVICE_LED_TOPIC_DESIRED, help="The topic that contians the desired LED state messages.")
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

# create & init synchronization object
class LockedData(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.disconnect_called = False

locked_data = LockedData()

# Using globals to simplify sample code
is_sample_done = threading.Event()

# LED states
LED_LIT = 1
LED_OFF = 0
LED_STATES = [LED_OFF, LED_LIT]
LED_COLORS = ["Red","Green","Blue"]

# These need to agree with the LED & button wiring
GPIO_LED_PINS = [16,20,21]
GPIO_BTN_PINS = [5,6,13]

DEFAULT_DEVICE_STATE = {
        "Red":      0,
        "Green":    0,
        "Blue":     0
}

# Using globals for command line parameters
args = parser.parse_args()

io.init_logging(getattr(io.LogLevel, args.verbosity), 'stderr')

# set device message topics
THIS_DEVICE = "demo_device/" + args.client_id
THIS_DEVICE_LED_TOPIC = THIS_DEVICE + "/led_state"
THIS_DEVICE_LED_TOPIC_DESIRED = THIS_DEVICE_LED_TOPIC + "/desired"
THIS_DEVICE_LED_TOPIC_REPORTED = THIS_DEVICE_LED_TOPIC + "/reported"
BUTTON_DEVICE_LED_TOPIC_DESIRED = args.led_state_topic

########################################
##  Hardware functions
########################################
#
#   Create and initialze an LED dictionary
#       gpio_led_pin: The GPIO pin that activates the LED (active HI). Must be in GPIO_LED_PINS.
#       gpio_btn_name: The Button.pin value of the button associated with the LED. (active LO)
#       color: The color of the button & LED. Must be in LED_COLORS
#       initial_state: The initial LED state: LED_OFF (default) | LED_LIT
#   returns
#       initialized LED dictionary
#
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


def set_device_state(device_led_state):
    global device_leds
    new_device_state = DEFAULT_DEVICE_STATE.copy()
    # for each LED in the device, update its state
    #  to match the state passed in the parameter
    for d_led in device_leds:
        # index by LED color
        led_color = device_leds[d_led]["color"]
        if device_led_state[led_color]:
            led_value = device_led_state[led_color]
        else:
            led_value = LED_OFF
        device_leds[d_led]["led"].value = led_value
        new_device_state[led_color] = device_leds[d_led]["led"].value
    return new_device_state


def get_device_state():
    global device_leds
    current_device_state = DEFAULT_DEVICE_STATE.copy()
    # for each LED in the device, update its state
    #  to match the state passed in the parameter
    for d_led in device_leds:
        # index by LED color
        led_color = device_leds[d_led]["color"]
        current_device_state[led_color] = device_leds[d_led]["led"].value
    return current_device_state


def btn_down (button):
    # this is the button press handler
    #   the GPIO library send this handler the button object
    #   of the button that fired it off.
    #   https://gpiozero.readthedocs.io/en/stable/api_input.html#button
    #
    #   when a button is pressed, set the device state so that the
    #       corresponding LED is lit and the others are turned off
    #
    global device_leds
    desired_device_state = DEFAULT_DEVICE_STATE.copy()
    # for each LED in the device, update its state
    #  to match the state passed in the parameter
    print("Button pressed: {}".format(str(button.pin)))
    for d_led in device_leds:
        # index by LED color
        led_color = device_leds[d_led]["color"]
        if (str(button.pin) == device_leds[d_led]["btn_name"]):
            desired_device_state[led_color] = LED_LIT

    print("  + Desired state: {}".format(json.dumps(desired_device_state).encode('utf-8')))
    publish_message (THIS_DEVICE_LED_TOPIC_DESIRED, desired_device_state)

    return


########################################
##  Basic connection functions
########################################

# Callback when connection is accidentally lost.
def on_connection_interrupted(connection, error, **kwargs):
    print("*** Connection interrupted. error: {}".format(error))


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
        print("  + Resubscribe results: {}".format(resubscribe_results))

        for topic, qos in resubscribe_results['topics']:
            if qos is None:
                sys.exit("  *** Server rejected resubscribe to topic: {}".format(topic))


def subscribe_to_topic(topic):
    #
    # Subscribe to the specified local_topic (which is appended to the app topics
    #
    print("Subscribing to topic '{}'...".format(topic))
    subscribe_future, packet_id = mqtt_connection.subscribe(
        topic=topic,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=on_message_received)
    # wait for subscription request to return and show the result
    subscribe_result = subscribe_future.result()
    print("  + Subscribed to '{}' with {}".format(topic, str(subscribe_result['qos'])))


# Callback when the subscribed topic receives a message
def on_message_received(topic, payload, **kwargs):
    print("Received message from topic '{}': {}".format(topic, payload))
    global device_leds

    # read the message to get the current LED state
    payload_data = json.loads(payload)

    # if this is a messaage from the button device that indicates a change in
    # the device state, set the leds to match the current state in the payload_data
    if topic == BUTTON_DEVICE_LED_TOPIC_DESIRED:
        new_device_state = set_device_state(payload_data)
        print("  + LED state set to {}".format(json.dumps(new_device_state).encode('utf-8')))

    # report the current state of this device
    publish_message(THIS_DEVICE_LED_TOPIC_REPORTED, new_device_state)


def publish_message (msg_topic, message_value):
    global mqtt_connection
    # format message_value as JSON string
    pub_message = json.dumps(message_value)

    print("Publishing message to topic '{}': {}".format(msg_topic, pub_message))
    pub_future, packet_id = mqtt_connection.publish(
        topic=msg_topic,
        payload=pub_message,
        qos=mqtt.QoS.AT_LEAST_ONCE)

    if (packet_id > 0):
        print("  + Message sent to {}, packet ID: {}".format(msg_topic, str(packet_id)))
    else:
        print("  *** Error publishing {}: '{}'".format(msg_topic, pub_message))

########################################
##  Shadow update functions
########################################

def on_update_shadow_accepted(response):
    # type: (iotshadow.UpdateShadowResponse) -> None
    # print("Shadow update accepted: '{}'.".format(json.dumps(reported_value).encode('utf-8')))
    try:
        reported_value = response.state.reported
        if reported_value:
            print("Shadow update reported accepted: '{}'.".format(json.dumps(reported_value).encode('utf-8')))

        desired_value = response.state.desired
        if desired_value:
           print("Shadow update desired accepted: '{}'.".format(json.dumps(desired_value).encode('utf-8')))
    except:
        print("Updated shadow response is missing the expected properties.")
    return


def on_update_shadow_rejected(error):
    # type: (iotshadow.ErrorResponse) -> None
    exit("Update request was rejected. code:{} message:'{}'".format(
        error.code, error.message))


def on_publish_update_shadow(future):
    #type: (Future) -> None
    try:
        future.result()
        print("Shadow update published.")
    except Exception as e:
        print("Failed to publish update request.")
        exit(e)


def update_reported_shadow_value():
    global iotshadow
    #
    # report the current device state back to AWS if this is the device
    #   with the buttons
    device_value = get_device_state()
    print("Updating reported shadow value to '{}'...".format(json.dumps(device_value).encode('utf-8')))
    request = iotshadow.UpdateShadowRequest(
        thing_name=thing_name,
        state=iotshadow.ShadowState(
            reported=device_value,
            desired=None
        )
    )
    future = shadow_client.publish_update_shadow(request, mqtt.QoS.AT_LEAST_ONCE)
    future.add_done_callback(on_publish_update_shadow)
    return

########################################
##  Get update functions
########################################


def on_get_shadow_accepted(response):
    # type: (iotshadow.GetShadowResponse) -> None
    # response contains the current shadow document from AWS
    try:
        print("Finished getting initial shadow state.")

        with locked_data.lock:
            if locked_data.shadow_value is not None:
                print("  Ignoring initial query because a delta event has already been received.")
                return

        if response.state:
            # there's a state object
            # see if there's a desired value meaning a requested change
            #  has not been applied
            if response.state.desired:
                # the shadow document contains a delta object, which indicates
                # the desired state of the device is different from the last
                # reported device state
                desired_value = response.state.desired
                if desired_value:
                    # set the device to the desired state
                    print("  Shadow contains desired value '{}'.".format(json.dumps(desired_value).encode('utf-8')))
                    device_value = set_device_state(desired_value)
                    # and update the reported state of the device to the shadow
                    update_reported_shadow_value()
                    return

            #   see if there's a reported value.
            if response.state.reported:
                # the shadow document contains a reported object, which indicates
                # the last reported device state and that no change to that state
                # has been requested.
                reported_value = response.state.reported
                if reported_value:
                    print("  Shadow contains reported value '{}'.".format(json.dumps(reported_value).encode('utf-8')))
                    device_value = set_device_value (reported_value)
                    return

        #
        # if the shadow contains no device state information, reset the device
        #  to the defaults.
        print("  Shadow document '{}' is not recognized. Setting defaults...".format(json.dumps(response).encode('utf-8')))
        device_value = set_device_state_to_message(SHADOW_VALUE_DEFAULT)
        set_new_shadow_value(device_value)
        return

    except Exception as e:
        exit(e)


def on_get_shadow_rejected(error):
    # type: (iotshadow.ErrorResponse) -> None
    if error.code == 404:
        #  no shadow document exists so create a default one
        print("Thing has no shadow document. Creating with defaults...")
        device_value = set_device_state_to_message(SHADOW_VALUE_DEFAULT)
        set_new_shadow_value(device_value)
    else:
        exit("Get request was rejected. code:{} message:'{}'".format(
            error.code, error.message))



########################################
##  App process functions
########################################

def user_input_thread_fn():
    while True:
        try:
            # Read user input
            try:
                new_value = raw_input() # python 2 only
            except NameError:
                new_value = input() # python 3 only

            # If user wants to quit sample, then quit.
            # Otherwise change the shadow value.
            if new_value in ['exit', 'quit']:
                exit("User has quit")
                break

        except Exception as e:
            print("*** Exception on input thread.")
            exit(e)
            break


# Function for gracefully quitting this sample
def exit(msg_or_exception):
    if isinstance(msg_or_exception, Exception):
        print("*** Exiting sample due to exception.")
        traceback.print_exception(msg_or_exception.__class__, msg_or_exception, sys.exc_info()[2])
    else:
        print("Exiting sample app:", msg_or_exception)

    with locked_data.lock:
        if not locked_data.disconnect_called:
            print("Disconnecting...")
            locked_data.disconnect_called = True
            future = mqtt_connection.disconnect()
            future.add_done_callback(on_disconnected)


def on_disconnected(disconnect_future):
    # type: (Future) -> None
    print("  + Disconnected.")

    # Signal that sample is finished
    is_sample_done.set()


########################################
##  Main app body
########################################

if __name__ == '__main__':

    # Spin up resources
    event_loop_group = io.EventLoopGroup(1)
    host_resolver = io.DefaultHostResolver(event_loop_group)
    client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)

    #initialize buttons
    red_btn = Button(5, bounce_time=0.1)
    grn_btn = Button(6, bounce_time=0.1)
    blu_btn = Button(13, bounce_time=0.1)

    # assign button press handlers
    red_btn.when_pressed = btn_down
    grn_btn.when_pressed = btn_down
    blu_btn.when_pressed = btn_down

    # intialize LEDs and set to off (the default)
    device_leds = {
        "Red": create_led(16, str(red_btn.pin), "Red"),
        "Green": create_led(20, str(grn_btn.pin), "Green"),
        "Blue": create_led(21, str(blu_btn.pin), "Blue")
    }

    # initialize device state
    device_state = set_device_state(DEFAULT_DEVICE_STATE)

    # open connection to AWS IoT server
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

    shadow_client = iotshadow.IotShadowClient(mqtt_connection)
    # Wait for connection to be fully established.
    # Note that it's not necessary to wait, commands issued to the
    # mqtt_connection before its fully connected will simply be queued.
    # But this sample waits here so it's obvious when a connection
    # fails or succeeds.
    connected_future.result()
    print("Connected!")

    try:
        # Subscribe to device messages
        #  listen for desired states from the button device
        #### subscribe_to_topic(BUTTON_DEVICE_LED_TOPIC_DESIRED)

        # Subscribe
        subscribe_topic = "demo_device/#"
        print("Subscribing to topic '{}'...".format(subscribe_topic))
        subscribe_future, packet_id = mqtt_connection.subscribe(
            topic=subscribe_topic,
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=on_device_topic_received)

        subscribe_result = subscribe_future.result()
        print("Subscribed with {}".format(str(subscribe_result['qos'])))


        # Subscribe to necessary topics.
        # Note that is **is** important to wait for "accepted/rejected" subscriptions
        # to succeed before publishing the corresponding "request".
        print("Subscribing to Delta events...")
        delta_subscribed_future, _ = shadow_client.subscribe_to_shadow_delta_updated_events(
            request=iotshadow.ShadowDeltaUpdatedSubscriptionRequest(thing_name=args.thing_name),
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=on_shadow_delta_updated)

        # Wait for subscription to succeed
        delta_subscribed_future.result()

        if update_reported_value_on_server():
            # only the buttons device updates the shadow on the server
            print("Subscribing to Update responses...")
            update_accepted_subscribed_future, _ = shadow_client.subscribe_to_update_shadow_accepted(
                request=iotshadow.UpdateShadowSubscriptionRequest(thing_name=args.thing_name),
                qos=mqtt.QoS.AT_LEAST_ONCE,
                callback=on_update_shadow_accepted)

            update_rejected_subscribed_future, _ = shadow_client.subscribe_to_update_shadow_rejected(
                request=iotshadow.UpdateShadowSubscriptionRequest(thing_name=args.thing_name),
                qos=mqtt.QoS.AT_LEAST_ONCE,
                callback=on_update_shadow_rejected)

            # Wait for subscriptions to succeed
            update_accepted_subscribed_future.result()
            update_rejected_subscribed_future.result()

        print("Subscribing to Get responses...")
        get_accepted_subscribed_future, _ = shadow_client.subscribe_to_get_shadow_accepted(
            request=iotshadow.GetShadowSubscriptionRequest(thing_name=args.thing_name),
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=on_get_shadow_accepted)

        get_rejected_subscribed_future, _ = shadow_client.subscribe_to_get_shadow_rejected(
            request=iotshadow.GetShadowSubscriptionRequest(thing_name=args.thing_name),
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=on_get_shadow_rejected)

        # Wait for subscriptions to succeed
        get_accepted_subscribed_future.result()
        get_rejected_subscribed_future.result()

        # The rest of the sample runs asyncronously.

        # Issue request for shadow's current state.
        # The response will be received by the on_get_accepted() callback
        print("Requesting current shadow state...")
        publish_get_future = shadow_client.publish_get_shadow(
            request=iotshadow.GetShadowRequest(thing_name=args.thing_name),
            qos=mqtt.QoS.AT_LEAST_ONCE)

        # Ensure that publish succeeds
        publish_get_future.result()

        # A "daemon" thread won't prevent the program from shutting down.
        print("Waiting for messages. Enter 'exit' to end program.")
        user_input_thread = threading.Thread(target=user_input_thread_fn, name='user_input_thread')
        user_input_thread.daemon = True
        user_input_thread.start()

    except Exception as e:
        exit(e)

    # Wait for the sample to finish (user types 'quit', or an error occurs)
    is_sample_done.wait()
