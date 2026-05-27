import boto3
import base64
import time

INSTANCE_ID = "i-0e6fff15b56704362"
REGION = "us-east-1"

ssm = boto3.client('ssm', region_name=REGION)
ec2 = boto3.client('ec2', region_name=REGION)

def send_command(command, description):
    print(f"Running: {description}...")
    response = ssm.send_command(
        InstanceIds=[INSTANCE_ID],
        DocumentName="AWS-RunShellScript",
        Parameters={'commands': [command]}
    )
    return response['Command']['CommandId']

def wait_for_command(command_id):
    while True:
        res = ssm.list_command_invocations(CommandId=command_id, Details=True)
        if res['CommandInvocations']:
            status = res['CommandInvocations'][0]['Status']
            if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                return status
        time.sleep(2)

def upload_file(local_path, remote_path):
    with open(local_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Use base64 to avoid escaping issues
    b64_content = base64.b64encode(content.encode()).decode()
    
    chunk_size = 40000
    chunks = [b64_content[i:i+chunk_size] for i in range(0, len(b64_content), chunk_size)]
    
    for i, chunk in enumerate(chunks):
        mode = ">" if i == 0 else ">>"
        cmd = f"echo -n '{chunk}' {mode} {remote_path}.b64"
        cmd_id = send_command(cmd, f"Uploading {local_path} (chunk {i+1}/{len(chunks)}) to {remote_path}.b64")
        wait_for_command(cmd_id)
        
    cmd = f"base64 -d {remote_path}.b64 > {remote_path} && rm {remote_path}.b64"
    return send_command(cmd, f"Decoding {remote_path}")

def deploy():
    print("--- Starting Remote Deployment ---")
    
    # 1. Ensure directories exist
    cmd_id = send_command("mkdir -p /home/ubuntu/apollo/static", "Creating directories")
    wait_for_command(cmd_id)
    
    # 2. Upload Files
    files_to_upload = [
        ("app.py", "/home/ubuntu/apollo/app.py"),
        ("llm_module.py", "/home/ubuntu/apollo/llm_module.py"),
        ("schema_utils.py", "/home/ubuntu/apollo/schema_utils.py"),
        ("intent_system.py", "/home/ubuntu/apollo/intent_system.py"),
        ("semantic_layer.json", "/home/ubuntu/apollo/semantic_layer.json"),
        ("etl_pipeline.py", "/home/ubuntu/apollo/etl_pipeline.py"),
        ("relational_to_graph_etl.py", "/home/ubuntu/apollo/relational_to_graph_etl.py"),
        ("agent_architectures.py", "/home/ubuntu/apollo/agent_architectures.py"),
        ("context_compactor.py", "/home/ubuntu/apollo/context_compactor.py"),
        ("retrieval_validator.py", "/home/ubuntu/apollo/retrieval_validator.py"),
        ("import_ontology.py", "/home/ubuntu/apollo/import_ontology.py"),
        ("setup_vector_index.py", "/home/ubuntu/apollo/setup_vector_index.py"),
        ("static/index.html", "/home/ubuntu/apollo/static/index.html"),
        ("requirements.txt", "/home/ubuntu/apollo/requirements.txt"),
        ("shapes.ttl", "/home/ubuntu/apollo/shapes.ttl"),
        ("apollo5.ttl", "/home/ubuntu/apollo/apollo5.ttl")
    ]
    
    for local, remote in files_to_upload:
        cmd_id = upload_file(local, remote)
        wait_for_command(cmd_id)
    
    # 3. Install and Run
    launch_cmd = """
    cd /home/ubuntu/apollo
    sudo apt-get update
    sudo apt-get install -y python3-pip
    pip3 install -r requirements.txt
    sudo pkill -f uvicorn || true
    nohup uvicorn app:app --host 0.0.0.0 --port 8000 > /home/ubuntu/apollo/app.log 2>&1 &
    """
    send_command(launch_cmd, "Installing dependencies and starting server")
    
    print("\n" + "="*50)
    print("DEPLOYMENT SIGNAL SENT")
    print("="*50)
    print(f"Access Link: http://44.202.98.128:8000")
    print("Note: Installation may take 1-2 minutes on the server.")
    print("="*50)

if __name__ == "__main__":
    deploy()
