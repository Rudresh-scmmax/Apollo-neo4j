import boto3
import time
import sys

# AWS Configuration
REGION = "us-east-1"
AMI_ID = "ami-00403f401ee6a4b98" # Ubuntu 22.04 LTS in us-east-1
INSTANCE_TYPE = "t3.medium"
KEY_NAME = "cas_poc"
SG_NAME = "neo4j-apollo-sg"

# User Data script to install Neo4j + n10s
USER_DATA = """#!/bin/bash
set -e

# Update and install dependencies
apt-get update -y
apt-get install -y openjdk-17-jdk wget curl gnupg apt-transport-https

# Install Neo4j 5.x
wget -O - https://debian.neo4j.com/neotechnology.gpg.key | gpg --dearmor -o /etc/apt/keyrings/neotechnology.gpg
echo 'deb [signed-by=/etc/apt/keyrings/neotechnology.gpg] https://debian.neo4j.com stable 5' | tee /etc/apt/sources.list.d/neo4j.list
apt-get update -y
apt-get install -y neo4j

# Download n10s plugin (ver 5.18.0)
wget https://github.com/neo4j-labs/neosemantics/releases/download/5.18.0/neosemantics-5.18.0.jar -P /var/lib/neo4j/plugins/

# Configure Neo4j
cat >> /etc/neo4j/neo4j.conf <<EOF
server.default_listen_address=0.0.0.0
dbms.security.procedures.unrestricted=n10s.*,apoc.*
dbms.security.procedures.allowlist=n10s.*,apoc.*
server.http.listen_address=:7474
server.bolt.listen_address=:7687
EOF

# Ensure Neo4j has permissions for plugins
chown neo4j:neo4j /var/lib/neo4j/plugins/neosemantics-5.18.0.jar

# Restart and enable Neo4j
systemctl enable neo4j
systemctl restart neo4j
"""

def deploy():
    ec2 = boto3.client('ec2', region_name=REGION)
    
    print(f"--- Deploying Neo4j to AWS ({REGION}) ---")
    
    # 1. Handle Security Group
    try:
        print(f"Ensuring Security Group '{SG_NAME}' exists...")
        vpcs = ec2.describe_vpcs(Filters=[{'Name': 'is-default', 'Values': ['true']}])
        vpc_id = vpcs['Vpcs'][0]['VpcId']
        
        try:
            sg = ec2.create_security_group(GroupName=SG_NAME, Description="Neo4j Server Access", VpcId=vpc_id)
            sg_id = sg['GroupId']
            print(f"Created Security Group: {sg_id}")
            
            ec2.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[
                    {'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                    {'IpProtocol': 'tcp', 'FromPort': 7474, 'ToPort': 7474, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                    {'IpProtocol': 'tcp', 'FromPort': 7687, 'ToPort': 7687, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
                ]
            )
        except ec2.exceptions.ClientError as e:
            if 'InvalidGroup.Duplicate' in str(e):
                sgs = ec2.describe_security_groups(GroupNames=[SG_NAME])
                sg_id = sgs['SecurityGroups'][0]['GroupId']
                print(f"Using existing Security Group: {sg_id}")
            else:
                raise e

        # 2. Launch Instance
        print(f"Launching {INSTANCE_TYPE} instance...")
        instances = ec2.run_instances(
            ImageId=AMI_ID,
            InstanceType=INSTANCE_TYPE,
            KeyName=KEY_NAME,
            SecurityGroupIds=[sg_id],
            MinCount=1,
            MaxCount=1,
            UserData=USER_DATA,
            TagSpecifications=[{
                'ResourceType': 'instance',
                'Tags': [{'Key': 'Name', 'Value': 'Apollo-Neo4j-Prod'}]
            }]
        )
        
        instance_id = instances['Instances'][0]['InstanceId']
        print(f"Successfully launched instance: {instance_id}")
        
        # 3. Wait for Public IP
        print("Waiting for instance to initialize and get Public IP...")
        public_ip = None
        for _ in range(20):
            desc = ec2.describe_instances(InstanceIds=[instance_id])
            inst = desc['Reservations'][0]['Instances'][0]
            if 'PublicIpAddress' in inst:
                public_ip = inst['PublicIpAddress']
                break
            time.sleep(5)
            
        if not public_ip:
            print("Timed out waiting for Public IP. Please check AWS Console.")
            return

        print("\n" + "="*60)
        print("NEO4J DEPLOYMENT INITIALIZED")
        print("="*60)
        print(f"Public IP:      {public_ip}")
        print(f"Neo4j Browser:  http://{public_ip}:7474")
        print(f"Bolt URL:       bolt://{public_ip}:7687")
        print("-" * 60)
        print("LOGIN CREDENTIALS:")
        print("Username:       neo4j")
        print(f"Password:       {instance_id} (Instance ID)")
        print("-" * 60)
        print("IMPORTANT: Wait ~5 minutes for the installation to complete.")
        print("Then run 'CALL n10s.graphconfig.init()' to verify n10s.")
        print("="*60 + "\n")

    except Exception as e:
        print(f"Error during deployment: {e}")

if __name__ == "__main__":
    deploy()
