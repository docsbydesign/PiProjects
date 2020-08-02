set +x
if [ -z "$1" ]; then
  echo "Enter the name of the thing you want to create."
  echo "For example:"
  echo "  sh $0 my-iot-thing"
  exit
fi
#
# Create the thing object for this device
#
THING_NAME=$1
#
echo "aws iot create-thing --thing-name $THING_NAME"
aws iot create-thing --thing-name $THING_NAME
#
# Crete the directory for the security files
#
CERTS_DIR=~/certs
if [ ! -d "$CERTS_DIR" ]; then
  echo "mkdir $CERTS_DIR"
  mkdir $CERTS_DIR
fi
#
# Download the Root CA file
#
ROOT_CA_FILE=~/certs/Amazon-root-CA-1.pem
if [ ! -f "$ROOT_CA_FILE" ]; then
  echo "curl -o $ROOT_CA_FILE https://www.amazontrust.com/repository/AmazonRootCA1.pem"
  curl -o $ROOT_CA_FILE \
      https://www.amazontrust.com/repository/AmazonRootCA1.pem
fi
#
#   Create the access policy for this device
#
POLICY_FILE=~/certs/Generic_Device_Policy.json
if [ ! -f "$POLICY_FILE" ]; then
  echo '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["iot:Publish","iot:Subscribe","iot:Receive","iot:Connect"],"Resource":["*"]}]}' > $POLICY_FILE
fi
#
#   test to see if the policy exists, and create it if it doesn't
#
GENERIC_POLICY_NAME=Generic_Device_Policy
#
#  $GENERIC_POLICY will be empty if the policy exists
#
GENERIC_POLICY=$(aws iot get-policy --policy-name $GENERIC_POLICY_NAME | grep error)
# if $GENERIC_POLICY is not empty, that means there was an error so create
#   a new policy
if [ -n "$GENERIC_POLICY" ]; then
  aws iot create-policy \
      --policy-name $GENERIC_POLICY_NAME \
      --policy-document file://$POLICY_FILE
else
  echo "Policy: $GENERIC_POLICY_NAME already exists"
fi
#
#   Create the device certificate
#
CERTIFICATE_ARN=$(aws iot create-keys-and-certificate --set-as-active --certificate-pem-outfile ~/certs/device.pem.crt --public-key-outfile ~/certs/public.pem.key --private-key-outfile ~/certs/private.pem.key | grep certificateArn | sed -r 's/\s*"certificateArn": "//g' | sed -r 's/[", ]*//g')
echo "Certificate: $CERTIFICATE_ARN created"
#
# if the certificate was created, then attach the thing and the policy to it
#
echo "aws iot attach-thing-principal --thing-name $THING_NAME --principal $CERTIFICATE_ARN"
aws iot attach-thing-principal \
    --thing-name $THING_NAME \
    --principal $CERTIFICATE_ARN
#
echo "aws iot attach-policy --policy-name $GENERIC_POLICY_NAME --target $CERTIFICATE_ARN"
aws iot attach-policy \
    --policy-name $GENERIC_POLICY_NAME \
    --target $CERTIFICATE_ARN
