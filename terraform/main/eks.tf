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

output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}
