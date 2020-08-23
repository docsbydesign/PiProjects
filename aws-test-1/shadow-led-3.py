# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.

from __future__ import absolute_import
from __future__ import print_function
import argparse
from awscrt import auth, io, mqtt, http
from awsiot import iotshadow
from awsiot import mqtt_connection_builder
from concurrent.futures import Future
import sys
import threading
import traceback
from uuid import uuid4
from gpiozero import LED, Button
from signal import pause
import json
import pprint

# - Overview -
# This sample uses the AWS IoT Device Shadow Service to keep a property in
# sync between device and server. Imagine a light whose color may be changed
# through an app, or set by a local user.
#
# - Instructions -
# Once connected, type a value in the terminal and press Enter to update
# the property's "reported" value. The sample also responds when the "desired"
# value changes on the server. To observe this, edit the Shadow document in
# the AWS Console and set a new "desired" value.
#
# - Detail -
# On startup, the sample requests the shadow document to learn the property's
# initial state. The sample also subscribes to "delta" events from the server,
# which are sent when a property's "desired" value differs from its "reported"
# value. When the sample learns of a new desired value, that value is changed
# on the device and an update is sent to the server with the new "reported"
# value.

parser = argparse.ArgumentParser(description="Device Shadow sample keeps a property in sync across client and server")
parser.add_argument('--endpoint', required=True, help="Your AWS IoT custom endpoint, not including a port. " +
                                                      "Ex: \"w6zbse3vjd5b4p-ats.iot.us-west-2.amazonaws.com\"")
parser.add_argument('--cert',  help="File path to your client certificate, in PEM format")
parser.add_argument('--key', help="File path to your private key file, in PEM format")
parser.add_argument('--root-ca', help="File path to root certificate authority, in PEM format. " +
                                      "Necessary if MQTT server uses a certificate that's not already in " +
                                      "your trust store")
parser.add_argument('--client-id', default="test-" + str(uuid4()), help="Client ID for MQTT connection.")
parser.add_argument('--thing-name', required=True, help="The name assigned to your IoT Thing")
parser.add_argument('--shadow-property', default="color", help="Name of property in shadow to keep in sync")
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
is_sample_done = threading.Event()

mqtt_connection = None
shadow_client = None
thing_name = ""

device_state = {
        "Red":      0,
        "Green":    0,
        "Blue":     0
}

SHADOW_VALUE_DEFAULT = device_state

class LockedData(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.shadow_value = None
        self.disconnect_called = False

locked_data = LockedData()

#
#   Create and initialize an LED object and its local metadata
#       returns local_LED object
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


#
#   Set the device LEDs to match the state specified in the JSON payload string
#       Returns current device state as message payload object
#
def set_device_state_to_message(payload):
    print("Set device to: {}".format(json.dumps(payload).encode('utf-8')))
    global device_leds

    # set the leds to match the current state in the payload_data
    for d_led in device_leds:
        # set the LED value (on/off) to the value specified in the message for that LED
        #  The LEDs are identified by their color in the message
        device_leds[d_led]["led"].value = payload[device_leds[d_led]["color"]]
        # set the actual LED's state to that of its value in the local object
        device_leds[d_led]["state"] = device_leds[d_led]["led"].value

    #
    #   Sync the local device state to  that of the LEDs
    #
    device_state["Red"] = device_leds["Red"]["state"]
    device_state["Green"] = device_leds["Green"]["state"]
    device_state["Blue"] = device_leds["Blue"]["state"]
    #
    #   return the device state as object
    return device_state



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


# this is the button press handler
#   when a button is pressed, set the device state so that the
#       corresponding LED is lit and the others are turned off
#
#  set the LED state to match the button pressed
#   and update the local device state
def btn_down (button):
    global args
    new_led_state = SHADOW_VALUE_DEFAULT
#    new_led_state["Red"] = device_leds["Red"]["state"]
#    new_led_state["Green"] = device_leds["Green"]["state"]
#    new_led_state["Blue"] = device_leds["Blue"]["state"]

    for d_led in device_leds:
        led_color = device_leds[d_led]["color"]
        if str(device_leds[d_led]["btn_name"]) == str(button.pin) :
            new_led_state[led_color] = 1
        else:
            # turn off all other LEDs
            new_led_state[led_color] = 0

    # publish a normal MQTT message with the requested device state
    topic = "demo_device/" + args.client_id + "/button_state"
    publish_message (topic, new_led_state)
    #
    #   The device doesn't send a shadow update message,
    #       Instead, there's a rule that catches the
    #       button_state topic and republishes the shadow
    #       update message
    #
    return


# Function for gracefully quitting this sample
def exit(msg_or_exception):
    if isinstance(msg_or_exception, Exception):
        print("Exiting sample due to exception.")
        traceback.print_exception(msg_or_exception.__class__, msg_or_exception, sys.exc_info()[2])
    else:
        print("Exiting sample:", msg_or_exception)

    with locked_data.lock:
        if not locked_data.disconnect_called:
            print("Disconnecting...")
            locked_data.disconnect_called = True
            future = mqtt_connection.disconnect()
            future.add_done_callback(on_disconnected)


def on_disconnected(disconnect_future):
    # type: (Future) -> None
    print("Disconnected.")

    # Signal that sample is finished
    is_sample_done.set()


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
            if response.state.desired:
                # the shadow document contains a delta object, which indicates
                # the desired state of the device is different from the last
                # reported device state
                desired_value = response.state.desired
                if desired_value:
                    # set the device to the desired state
                    print("  Shadow contains desired value '{}'.".format(json.dumps(desired_value).encode('utf-8')))
                    device_value = set_device_state_to_message(desired_value)
                    set_new_shadow_value(device_value)
                    return

            if response.state.reported:
                # the shadow document contains a reported object, which indicates
                # the last reported device state and that no change to that state
                # has been requested.
                reported_value = response.state.reported
                if reported_value:
                    print("  Shadow contains reported value '{}'.".format(json.dumps(reported_value).encode('utf-8')))
                    device_value = set_device_state_to_message(reported_value)
                    set_new_shadow_value(device_value)
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


def on_shadow_delta_updated(delta):
    # type: (iotshadow.ShadowDeltaUpdatedEvent) -> None
    try:
        print("Received shadow delta event.")
        if delta.state:
            delta_value = SHADOW_VALUE_DEFAULT
            for led_color in delta.state:
                delta_value[led_color] = delta.state[led_color]

            print("  Delta reports that desired value is '{}'. Changing local value...".format(json.dumps(delta_value).encode('utf-8')))
            device_value = set_device_state_to_message(delta_value)
            set_new_shadow_value(device_value)
        else:
            print("  Delta reports '{}'. Resetting defaults...".format(json.dumps(delta.state).encode('utf-8')))
            device_value = set_device_state_to_message(SHADOW_VALUE_DEFAULT)
            set_new_shadow_value(device_value)
            return

    except Exception as e:
        exit(e)


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


def on_update_shadow_rejected(error):
    # type: (iotshadow.ErrorResponse) -> None
    exit("Update request was rejected. code:{} message:'{}'".format(
        error.code, error.message))


def device_values_are_equal(value1, value2):
    print("testing {} == {}".format(json.dumps(value1).encode('utf-8'),json.dumps(value2).encode('utf-8')))
    try:
        if ((value1["Red"] == value2["Red"]) and
            (value1["Green"] == value2["Green"]) and
            (value1["Blue"] == value2["Blue"])):
            return True
        else:
            return False
    except:
        return False

#
#   Change local shadow and optionally the device to match value parameter
#
def set_new_shadow_value(value):
    global device_state
    global args
    with locked_data.lock:
        #
        #   update local shadow value to match device
        print("Changed local shadow value to '{}'.".format(json.dumps(value).encode('utf-8')))
        locked_data.shadow_value = value

        # publish a normal MQTT message with the current LED state
        topic = "demo_device/" + args.client_id + "/led_state"
        print("Sending device state message to {}: '{}'.".format(topic, json.dumps(value).encode('utf-8')))
        publish_message (topic, value)

    if update_reported_value_on_server():
        #
        # report the current device state back to AWS if this is the device
        #   with the buttons
        print("Updating reported shadow value to '{}'...".format(json.dumps(value).encode('utf-8')))
        request = iotshadow.UpdateShadowRequest(
            thing_name=thing_name,
            state=iotshadow.ShadowState(
                reported=value,
                desired=None
            )
        )
        future = shadow_client.publish_update_shadow(request, mqtt.QoS.AT_LEAST_ONCE)
        future.add_done_callback(on_publish_update_shadow)


# return true if client is "buttons"
#  only the client with the buttons can update "reported" value
#   on the shadoow on the server
def update_reported_value_on_server():
    global args
    if args.client_id == 'buttons':
        return True
    else:
        return False


# Callback when the subscribed topic receives a message
def on_device_topic_received(topic, payload, **kwargs):
    print("++ Device topic message from topic '{}': {}".format(topic, payload))


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
#            else:
#                change_shadow_value(new_value)

        except Exception as e:
            print("Exception on input thread.")
            exit(e)
            break


if __name__ == '__main__':
    # Process input args
    args = parser.parse_args()
    thing_name = args.thing_name
    io.init_logging(getattr(io.LogLevel, args.verbosity), 'stderr')

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

    # initialize the local device state
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

        # Launch thread to handle user input.
        # A "daemon" thread won't prevent the program from shutting down.
        print("Launching thread to read user input...")
        user_input_thread = threading.Thread(target=user_input_thread_fn, name='user_input_thread')
        user_input_thread.daemon = True
        user_input_thread.start()

    except Exception as e:
        exit(e)

    # Wait for the sample to finish (user types 'quit', or an error occurs)
    is_sample_done.wait()
