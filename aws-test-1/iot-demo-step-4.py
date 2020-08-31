# Adapted from https://github.com/aws/aws-iot-device-sdk-python-v2/blob/master/samples/pubsub.py
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.

from __future__ import absolute_import
from __future__ import print_function
import argparse
from awscrt import io, mqtt, auth, http
from awsiot import iotshadow
from awsiot import mqtt_connection_builder
from concurrent.futures import Future
import traceback
import sys
import threading
from uuid import uuid4
from gpiozero import LED, Button
import json

'''
This program runs on both a button device and an led device.

    button device:
        On btn_down:
            publish button state in topic demo_device/buttons/led_state/desired
                send a message with the desired state of the LEDs

        Subscribe to:
            demo_device/buttons/led_state/pending (led state object)
                set LEDs to blinking to indicate receipt of button state
            demo_device/buttons/led_state/reported (led state object)
                set LEDs to steady to indicate LEDs have been set to desired state
            $aws/things/leds_demo_device/shadow/get/accepted (get shadow)
                on this message, update device to match current shadow state
                publish the reported state
            $aws/things/leds_demo_device/shadow/get/rejected (get shadow)
                on this message, display error getting current shadow state
        publish:
            $aws/things/leds_demo_device/shadow/update (reported state)
                to report current LED state to shadow

    led device:
        subscribe to:
            $aws/things/leds_demo_device/shadow/get/accepted (get shadow)
                on this message, update device to match current shadow state
                publish the reported state
            $aws/things/leds_demo_device/shadow/get/rejected (get shadow)
                on this message, display error getting current shadow state

            $aws/things/leds_demo_device/shadow/update/delta (shadow-delta)
                on this message, update device to match desired shadow state
                publish the reported state

            $aws/things/leds_demo_device/shadow/update/accepted (update shadow)
                confirms update was successful
            $aws/things/leds_demo_device/shadow/update/rejected (update shadow)
                confirms update was not successful
        publish:
            $aws/things/leds_demo_device/shadow/update (reported state)
                to report current LED state to shadow

The program also expects these IoT Topic Rules:

    On_button_press
        republish demo_device/buttons/led_state/pending (led state object)
        republish $aws/things/leds_demo_device/shadow/update (desired state)

    On_shadow_updated (with reported state)
        republish demo_device/buttons/led_state/reported (led state object)

'''


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

parser = argparse.ArgumentParser(description="Use MQTT messages to emulate Step 4 of the AWS IoT learning demo.")
parser.add_argument('--endpoint', required=True, help="Your AWS IoT custom endpoint, not including a port. " +
                                        "Ex: \"abcd123456wxyz-ats.iot.us-east-1.amazonaws.com\"")
parser.add_argument('--cert', help="File path to your client certificate, in PEM format.")
parser.add_argument('--key', help="File path to your private key, in PEM format.")
parser.add_argument('--root-ca', help="File path to root certificate authority, in PEM format. " +
                                        "Necessary if MQTT server uses a certificate that's not already in " +
                                        "your trust store.")
parser.add_argument('--thing-name', required=True, help="The name assigned to your IoT Thing. " +
                                        "Button device thing names must start with 'buttons' and " +
                                        "LED device thing names must start with 'led'." )
parser.add_argument('--led-thing-name', default=None, help="The thing name of the LED device. " +
                                         "If omitted, the device's thing name is used.")
parser.add_argument('--client-id', default="button", help="Client ID of this device for MQTT connection." +
                                        "Must be unique in the account and Region." )
parser.add_argument('--use-websocket', default=False, action='store_true',
                                        help="To use a websocket instead of raw mqtt. If you " +
                                        "specify this option you must specify a region for signing, " +
                                        "you can also enable proxy mode.")
parser.add_argument('--signing-region', default='us-east-1', help="If you specify --use-web-socket, this " +
                                        "is the region that will be used for computing the Sigv4 signature")
parser.add_argument('--proxy-host', help="Hostname for proxy to connect to. Note: if you use this feature, " +
                                        "you will likely need to set --root-ca to the ca for your proxy.")
parser.add_argument('--proxy-port', type=int, default=8080, help="Port for proxy to connect to.")
parser.add_argument('--verbosity', choices=[x.name for x in io.LogLevel], default=io.LogLevel.NoLogs.name,
                                        help='Logging level')

# create & init synchronization object
class LockedData(object):
    # no local shadow document is kept.
    # the device state is used as the local store of the current state
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

DEVICE_TYPE_BUTTON = "buttons"
DEVICE_TYPE_LED = "leds"
DEVICE_TYPES = [DEVICE_TYPE_BUTTON, DEVICE_TYPE_LED]

DEFAULT_DEVICE_STATE = {
        "Red":      0,
        "Green":    0,
        "Blue":     0
}

# Using globals for command line parameters
args = parser.parse_args()

# initialize the led_thing_name value
if not args.led_thing_name:
    args.led_thing_name = args.thing_name

io.init_logging(getattr(io.LogLevel, args.verbosity), 'stderr')

# set device message topics
THIS_DEVICE = "demo_device/" + args.client_id
THIS_DEVICE_LED_TOPIC = THIS_DEVICE + "/led_state"
THIS_DEVICE_BUTTON_TOPIC = THIS_DEVICE + "/button_state"
THIS_DEVICE_LED_TOPIC_DESIRED = THIS_DEVICE_LED_TOPIC + "/desired"
THIS_DEVICE_LED_TOPIC_PENDING = THIS_DEVICE_LED_TOPIC + "/pending"
THIS_DEVICE_LED_TOPIC_REPORTED = THIS_DEVICE_LED_TOPIC + "/reported"
THIS_DEVICE_BUTTON_TOPIC_REPORTED = THIS_DEVICE_BUTTON_TOPIC + "/reported"

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


def set_device_state(device_led_state, pending_state=False):
    global device_leds
    print("Setting device LEDs to: {}, pending: {}".format(json.dumps(device_led_state).encode('utf8'), str(pending_state)))
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
        if led_value and pending_state:
            # flash Pending LEDs
            device_leds[d_led]["led"].blink(0.05,0.05)
            new_device_state[led_color] = LED_LIT # show blinking as ON
        else:
            # display steady LEDs when ON
            device_leds[d_led]["led"].value = led_value
            new_device_state[led_color] = device_leds[d_led]["led"].value
    print("  + New device LED state: {}".format(json.dumps(new_device_state).encode('utf8')))
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


def device_values_are_equal(value1, value2):
    try:
        if ((value1["Red"] == value2["Red"]) and
            (value1["Green"] == value2["Green"]) and
            (value1["Blue"] == value2["Blue"])):
            return True
        else:
            return False
    except:
        return False


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

    if not device_values_are_equal(desired_device_state, get_device_state()):
        # if the LED for the button pressed is not already lit, publish the message
        print("  + Desired state: {}".format(json.dumps(desired_device_state).encode('utf-8')))
        publish_message (THIS_DEVICE_LED_TOPIC_DESIRED, desired_device_state)
    else:
        print("  + The LED for the button pressed is aleady lit. No message sent.")
    return


########################################
##  Basic connection functions
########################################

def publish_message (msg_topic, value):
    global mqtt_connection

    # format object as JSON to send as message string
    message = json.dumps(value)

    print("Publishing message to topic '{}': {}".format(msg_topic, message))
    pub_future, packet_id = mqtt_connection.publish(
        topic=msg_topic,
        payload=message,
        qos=mqtt.QoS.AT_LEAST_ONCE)
    # wait for response
    print("MQTT msg packet ID: {}".format(str(packet_id)))
    #print("MQTT publish finished. Packet ID: {}".format(json.dumps(pub_future).encode('utf-8')))


def subscribe_to_topic(topic, callback_fn):
    #
    # Subscribe to the specified MQTT topic
    #
    print("Subscribing to topic '{}'...".format(topic))
    subscribe_future, packet_id = mqtt_connection.subscribe(
        topic=topic,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=callback_fn)
    # wait for subscription request to return and show the result
    subscribe_result = subscribe_future.result()
    print("  + Subscribed to '{}' with {}".format(topic, str(subscribe_result['qos'])))


# Callback when connection is accidentally lost.
def on_connection_interrupted(connection, error, **kwargs):
    print("*** Connection interrupted. error: {}".format(error))


def on_disconnected(disconnect_future):
    # type: (Future) -> None
    print("  + Disconnected.")

    # Signal that sample is finished
    is_sample_done.set()


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


# Callback when the subscribed topic receives a message
def on_pending_message_received(topic, payload, **kwargs):
    print("Received pending message from topic '{}': {}".format(topic, payload))
    # read the message to get the current LED state
    payload_data = json.loads(payload)

    # if this is a messaage from the button device that indicates a change in
    # the device state, set the leds to match the current state in the payload_data
    new_device_state = set_device_state(payload_data, True)
    print("  + LED pending state set to {}".format(json.dumps(new_device_state).encode('utf-8')))
    # after updating the device, report its current state

    return


# Callback when the subscribed topic receives a message
def on_reported_message_received(topic, payload, **kwargs):
    print("Received message from topic '{}': {}".format(topic, payload))
    global device_leds
    global device_type

    try:
        # read the message to get the current LED state
        payload_data = json.loads(payload)

        # if this is a messaage from the button device that indicates a change in
        # the device state, set the leds to match the current state in the payload_data
        if "reported" in payload_data:
            new_device_state = set_device_state(payload_data["reported"])
            print("  + LED state set to {}".format(json.dumps(new_device_state).encode('utf-8')))
            # after updating the device, report its current state
            publish_message(THIS_DEVICE_BUTTON_TOPIC_REPORTED, new_device_state)
        else:
            print("  ** Payload not recognized: {}".format(payload))

    except Exception as e:
        print("  ** Exception reading payload: {}".format(payload))

    return

########################################
##  Shadow delta functions
########################################

def on_shadow_delta_updated(delta):
    # type: (iotshadow.ShadowDeltaUpdatedEvent) -> None
    try:
        print("Received shadow delta event.")
        if delta.state:
            delta_value = DEFAULT_DEVICE_STATE.copy()
            for led_color in delta.state:
                delta_value[led_color] = delta.state[led_color]

            print("  Delta reports that desired value is '{}'. Changing local value...".format(json.dumps(delta_value).encode('utf-8')))
            device_value = set_device_state(delta_value)
            update_reported_shadow_value()
        else:
            print("  Delta reports '{}'. Resetting defaults...".format(json.dumps(delta.state).encode('utf-8')))
            device_value = set_device_state(DEFAULT_DEVICE_STATE)
            update_reported_shadow_value()
            return

    except Exception as e:
        exit(e)

########################################
##  Shadow update functions
########################################

def update_reported_shadow_value():
    global iotshadow
    global args
    global device_type
    #
    #   Only LED device report their state to the Shadow
    #
    if device_type != DEVICE_TYPE_LED:
        print("No shadow updated because this is not an LED device.")
        return
    #
    # report the current device state back to AWS if this is the device
    #   with the buttons
    device_value = get_device_state()
    print("Updating reported shadow value to '{}'...".format(json.dumps(device_value).encode('utf-8')))
    request = iotshadow.UpdateShadowRequest(
        thing_name=args.thing_name,
        state=iotshadow.ShadowState(
            reported=device_value,
            desired=None
        )
    )
    future = shadow_client.publish_update_shadow(request, mqtt.QoS.AT_LEAST_ONCE)
    future.add_done_callback(on_publish_update_shadow)
    return


def on_publish_update_shadow(future):
    #type: (Future) -> None
    try:
        future.result()
        print("Shadow update published.")
    except Exception as e:
        print("Failed to publish update request.")
        exit(e)


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


########################################
##  Get update functions
########################################


def on_get_shadow_accepted(response):
    # type: (iotshadow.GetShadowResponse) -> None
    # response contains the current shadow document from AWS
    try:
        print("Finished getting initial shadow state.")

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
                # has been requested so just set the device to match and report
                # the value to update the document reported metadata
                reported_value = response.state.reported
                if reported_value:
                    print("  Shadow contains reported value '{}'.".format(json.dumps(reported_value).encode('utf-8')))
                    device_value = set_device_value (reported_value)
                    # and update the reported state of the device to the shadow
                    update_reported_shadow_value()
                    return

        #
        # if the shadow contains no device state information, reset the device
        #  to the defaults.
        print("  Shadow document '{}' is not recognized. Setting defaults...".format(json.dumps(response).encode('utf-8')))
        device_value = set_device_state(DEFAULT_DEVICE_STATE)
        # and update the reported state of the device to the shadow
        update_reported_shadow_value()
        return

    except Exception as e:
        exit(e)


def on_get_shadow_rejected(error):
    # type: (iotshadow.ErrorResponse) -> None
    if error.code == 404:
        #  no shadow document exists so create a default one
        print("Thing has no shadow document. Creating with defaults...")
        device_value = set_device_state(DEFAULT_DEVICE_STATE)
        # and update the reported state of the device to the shadow
        update_reported_shadow_value()
    else:
        exit("Get request was rejected. code:{} message:'{}'".format(
            error.code, error.message))


########################################
##  App process functions
########################################

def get_device_type(thing_name):
    if (thing_name[:7] == DEVICE_TYPE_BUTTON):
        return DEVICE_TYPE_BUTTON
    elif (thing_name[:4]) == DEVICE_TYPE_LED:
        return DEVICE_TYPE_LED
    else:
        return None


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

    device_type = get_device_type(args.thing_name)
    if not device_type:
        print("*** Device type not recognized: {}".format(args.thing_name))
        exit()

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

    connected_future = mqtt_connection.connect()

    shadow_client = iotshadow.IotShadowClient(mqtt_connection)
    # Wait for connection to be fully established.
    # Note that it's not necessary to wait, commands issued to the
    # mqtt_connection before its fully connected will simply be queued.
    # But this sample waits here so it's obvious when a connection
    # fails or succeeds.
    connected_future.result()
    print("Connected!")

    try:

        if device_type == DEVICE_TYPE_BUTTON:
            # subscribe to button device topics
            subscribe_to_topic(THIS_DEVICE_LED_TOPIC_REPORTED, on_reported_message_received)
            subscribe_to_topic(THIS_DEVICE_LED_TOPIC_PENDING, on_pending_message_received)

        elif device_type == DEVICE_TYPE_LED:
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

        #
        #   topics used by both button and LED devices
        #
        print("Subscribing to Get responses...")
        get_accepted_subscribed_future, _ = shadow_client.subscribe_to_get_shadow_accepted(
            request=iotshadow.GetShadowSubscriptionRequest(thing_name=args.led_thing_name),
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=on_get_shadow_accepted)

        get_rejected_subscribed_future, _ = shadow_client.subscribe_to_get_shadow_rejected(
            request=iotshadow.GetShadowSubscriptionRequest(thing_name=args.led_thing_name),
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=on_get_shadow_rejected)

        # Wait for subscriptions to succeed
        get_accepted_subscribed_future.result()
        get_rejected_subscribed_future.result()

        # The rest of the sample runs asyncronously.

        # Issue request for shadow's current state.
        # The response will be received by the on_get_accepted() callback
        print("Requesting current shadow state from {}...".format(args.led_thing_name))
        publish_get_future = shadow_client.publish_get_shadow(
            request=iotshadow.GetShadowRequest(thing_name=args.led_thing_name),
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
