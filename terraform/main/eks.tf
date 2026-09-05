module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  name               = "vaultly"
  kubernetes_version = "1.31"
  endpoint_public_access = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  enabled_log_types = ["api", "audit"]

  enable_irsa = true

  eks_managed_node_groups = {
    vaultly = {
      instance_types = ["t3.medium"]
      min_size     = 2
      max_size     = 2
      desired_size = 2
    }
  }

  tags = {
    Project = "vaultly"
  }
}

# Allow node SG to reach cluster API (ingress on the cluster SG)
resource "aws_security_group_rule" "node_to_cluster_api" {
  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  security_group_id        = module.eks.cluster_security_group_id
  source_security_group_id = module.eks.node_security_group_id
  description              = "Nodes to EKS API"
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}   