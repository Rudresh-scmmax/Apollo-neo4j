import boto3
import json

ec2 = boto3.client('ec2', region_name='us-east-1')
res = ec2.describe_instances(InstanceIds=['i-0e6fff15b56704362'])
groups = res['Reservations'][0]['Instances'][0]['SecurityGroups']
group_ids = [g['GroupId'] for g in groups]
rules = ec2.describe_security_groups(GroupIds=group_ids)

for g in rules['SecurityGroups']:
    print(f"Group: {g['GroupId']}")
    for r in g['IpPermissions']:
        from_port = r.get('FromPort')
        to_port = r.get('ToPort')
        ip_ranges = [ip['CidrIp'] for ip in r.get('IpRanges', [])]
        print(f"  {r['IpProtocol']} {from_port}-{to_port} from {ip_ranges}")
