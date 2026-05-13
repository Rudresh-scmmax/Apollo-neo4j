provider "aws" {
  region = "us-east-1"
}

# 1. Security Group
resource "aws_security_group" "apollo_sg" {
  name        = "apollo-procurement-sg"
  description = "Security group for Apollo Neo4j and Chatbot"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 7474
    to_port     = 7474
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 7687
    to_port     = 7687
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# 2. IAM Role for SSM
resource "aws_iam_role" "apollo_role" {
  name = "ApolloSSMRoleTF"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ssm_attach" {
  role       = aws_iam_role.apollo_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "bedrock_attach" {
  role       = aws_iam_role.apollo_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonBedrockFullAccess"
}

resource "aws_iam_instance_profile" "apollo_profile" {
  name = "ApolloInstanceProfileTF"
  role = aws_iam_role.apollo_role.name
}

# 3. EC2 Instance
resource "aws_instance" "apollo_server" {
  ami                  = "ami-00403f401ee6a4b98" # Ubuntu 22.04 LTS
  instance_type        = "t3.medium"
  key_name             = "cas_poc"
  iam_instance_profile = aws_iam_instance_profile.apollo_profile.name
  vpc_security_group_ids = [aws_security_group.apollo_sg.id]

  user_data = <<-EOF
              #!/bin/bash
              apt-get update -y
              apt-get install -y openjdk-17-jdk wget curl gnupg python3-pip

              # Install Neo4j
              wget -O - https://debian.neo4j.com/neotechnology.gpg.key | gpg --dearmor -o /etc/apt/keyrings/neotechnology.gpg
              echo 'deb [signed-by=/etc/apt/keyrings/neotechnology.gpg] https://debian.neo4j.com stable 5' | tee /etc/apt/sources.list.d/neo4j.list
              apt-get update -y
              apt-get install -y neo4j
              
              # Download n10s
              wget https://github.com/neo4j-labs/neosemantics/releases/download/5.18.0/neosemantics-5.18.0.jar -P /var/lib/neo4j/plugins/
              chown neo4j:neo4j /var/lib/neo4j/plugins/neosemantics-5.18.0.jar

              # Config Neo4j
              cat >> /etc/neo4j/neo4j.conf <<EOC
              server.default_listen_address=0.0.0.0
              dbms.security.procedures.unrestricted=n10s.*,apoc.*
              dbms.security.procedures.allowlist=n10s.*,apoc.*
              EOC

              systemctl enable neo4j
              systemctl restart neo4j
              EOF

  tags = {
    Name = "Apollo-Production-Server"
  }
}

output "chatbot_url" {
  value = "http://${aws_instance.apollo_server.public_ip}:8000"
}

output "neo4j_browser" {
  value = "http://${aws_instance.apollo_server.public_ip}:7474"
}
