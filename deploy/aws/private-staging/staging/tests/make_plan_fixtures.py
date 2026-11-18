#!/usr/bin/env python3
"""Regenerate the fixed plan fixtures in fixtures/ (synthetic `terraform show -json`
shape; placeholder account 111122223333; no real ID, ARN or address).

  python3 -I make_plan_fixtures.py   # rewrites fixtures/plan-*.json

The committed fixtures are the reference; tests/test_staging_tools.py checks the
verdict of each. Only the subset of attributes plan_check.py reads is filled in.
"""
import copy
import json
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TAGS = {"Project": "flh", "Component": "workbench-staging", "Run": "20261118T000000Z",
        "ExpiresAt": "2026-11-18T18:00:00Z", "ManagedBy": "terraform"}
P = "registry.terraform.io/hashicorp/aws"


def rc(address, after, actions=("create",), tagged=True, name_tag=None):
    rtype, name = address.split(".", 1)
    a = dict(after)
    if tagged:
        a["tags"] = {"Name": name_tag} if name_tag else {}
        a["tags_all"] = dict(TAGS, **({"Name": name_tag} if name_tag else {}))
    return {"address": address, "mode": "managed", "type": rtype, "name": name, "provider_name": P,
            "change": {"actions": list(actions), "before": None if actions == ("create",) else copy.deepcopy(a),
                       "after": a, "after_unknown": {}}}


def data(address):
    rtype, name = address[5:].split(".", 1)
    return {"address": address, "mode": "data", "type": rtype, "name": name, "provider_name": P,
            "change": {"actions": ["read"], "before": None, "after": {}, "after_unknown": {}}}


def base_changes():
    return [
        rc("aws_vpc.stg", {"cidr_block": "10.85.0.0/24", "enable_dns_support": True}, name_tag="flh-stg-vpc"),
        rc("aws_internet_gateway.stg", {}, name_tag="flh-stg-igw"),
        rc("aws_subnet.public", {"cidr_block": "10.85.0.0/24", "map_public_ip_on_launch": False}, name_tag="flh-stg-public"),
        rc("aws_route_table.public", {"route": [{"cidr_block": "0.0.0.0/0"}]}, name_tag="flh-stg-public"),
        rc("aws_route_table_association.public", {}, tagged=False),
        rc("aws_vpc_endpoint.s3", {"service_name": "com.amazonaws.us-east-1.s3", "vpc_endpoint_type": "Gateway"},
           name_tag="flh-stg-s3"),
        rc("aws_security_group.host", {"name": "flh-stg-host", "ingress": [], "egress": []}, name_tag="flh-stg-host"),
        rc("aws_vpc_security_group_egress_rule.https", {"ip_protocol": "tcp", "from_port": 443, "to_port": 443,
                                                         "cidr_ipv4": "0.0.0.0/0"}),
        rc("aws_s3_bucket.staging", {"bucket_prefix": "flh-stg-", "force_destroy": True}),
        rc("aws_s3_bucket_public_access_block.staging", {"block_public_acls": True, "block_public_policy": True,
                                                          "ignore_public_acls": True, "restrict_public_buckets": True},
           tagged=False),
        rc("aws_s3_bucket_ownership_controls.staging", {"rule": [{"object_ownership": "BucketOwnerEnforced"}]}, tagged=False),
        rc("aws_s3_bucket_server_side_encryption_configuration.staging",
           {"rule": [{"apply_server_side_encryption_by_default": [{"sse_algorithm": "AES256"}]}]}, tagged=False),
        rc("aws_s3_bucket_versioning.staging", {"versioning_configuration": [{"status": "Enabled"}]}, tagged=False),
        rc("aws_s3_bucket_lifecycle_configuration.staging", {"rule": [{"id": "expire-staging-objects"}]}, tagged=False),
        rc("aws_s3_bucket_policy.staging", {}, tagged=False),
        rc("aws_iam_role.host", {"name_prefix": "flh-stg-host-",
                                 "permissions_boundary": "arn:aws:iam::111122223333:policy/flh-stg-host-boundary"}),
        rc("aws_iam_role_policy.host", {"name": "flh-stg-host"}, tagged=False),
        rc("aws_iam_instance_profile.host", {"name_prefix": "flh-stg-host-"}),
        rc("aws_instance.host", {"ami": "ami-0123456789abcdef0", "instance_type": "t3.small",
                                 "associate_public_ip_address": True, "instance_initiated_shutdown_behavior": "terminate",
                                 "metadata_options": [{"http_endpoint": "enabled", "http_tokens": "required",
                                                       "http_put_response_hop_limit": 2}],
                                 "root_block_device": [{"encrypted": True, "volume_type": "gp3", "volume_size": 16}]},
           name_tag="flh-stg-host"),
        rc("aws_ebs_volume.data", {"size": 8, "type": "gp3", "encrypted": True}, name_tag="flh-stg-data"),
        rc("aws_volume_attachment.data", {"device_name": "/dev/sdf"}, tagged=False),
    ]


def datas():
    return [data(a) for a in ("data.aws_ec2_instance_type.selected", "data.aws_iam_policy.host_boundary",
                              "data.aws_caller_identity.current", "data.aws_iam_policy_document.bucket",
                              "data.aws_iam_policy_document.ec2_assume", "data.aws_iam_policy_document.host")]


def plan(changes, prior=None):
    return {"format_version": "1.2", "terraform_version": "1.16.6",
            "planned_values": {"root_module": {}},
            "prior_state": {"format_version": "1.0", "values": {"root_module": {"resources": prior or []}}},
            "resource_changes": datas() + changes,
            "configuration": {"provider_config": {"aws": {"name": "aws", "full_name": P}}}}


def as_state(changes):
    return [{"address": c["address"], "mode": "managed", "type": c["type"], "name": c["name"]} for c in changes]


def with_actions(changes, actions, only=None):
    out = []
    for c in copy.deepcopy(changes):
        if only is None or c["address"] in only:
            c["change"]["actions"] = list(actions)
            c["change"]["before"] = copy.deepcopy(c["change"]["after"])
            if actions == ("delete",):
                c["change"]["after"] = None
        out.append(c)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    fx = {}
    base = base_changes()
    fx["plan-create-safe.json"] = plan(base)
    fx["plan-update-noop-safe.json"] = plan(with_actions(base, ("no-op",)), prior=as_state(base))
    fx["plan-destroy-safe.json"] = plan(with_actions(base, ("delete",)), prior=as_state(base))
    # public ingress: an inbound 8080 rule from anywhere and a group carrying it
    bad = copy.deepcopy(base)
    for c in bad:
        if c["address"] == "aws_security_group.host":
            c["change"]["after"]["ingress"] = [{"from_port": 8080, "to_port": 8080, "protocol": "tcp",
                                                "cidr_blocks": ["0.0.0.0/0"]}]
    bad.append(rc("aws_vpc_security_group_ingress_rule.workbench", {"ip_protocol": "tcp", "from_port": 8080,
                                                                    "to_port": 8080, "cidr_ipv4": "0.0.0.0/0"}))
    fx["plan-unsafe-public-ingress.json"] = plan(bad)
    # an update that replaces the host and the data volume (for example a changed AZ or user data)
    upd = with_actions(base, ("no-op",))
    upd = [c if c["address"] not in ("aws_instance.host", "aws_ebs_volume.data", "aws_volume_attachment.data")
           else with_actions([c], ("delete", "create"))[0] for c in upd]
    fx["plan-unsafe-replace-data-volume.json"] = plan(upd, prior=as_state(base))
    # an update that replaces only the instance (user data changed): STOP unless explicitly allowed
    upd2 = with_actions(base, ("no-op",))
    upd2 = [c if c["address"] not in ("aws_instance.host", "aws_volume_attachment.data")
            else with_actions([c], ("create", "delete"))[0] for c in upd2]
    fx["plan-update-replace-instance.json"] = plan(upd2, prior=as_state(base))
    # unexpected resources: the demo's instance in this root, an Elastic IP and a DNS record
    unexp = copy.deepcopy(base) + [
        rc("aws_instance.demo", {"instance_type": "t4g.micro", "metadata_options": [{"http_tokens": "required"}],
                                 "root_block_device": [{"encrypted": True}],
                                 "instance_initiated_shutdown_behavior": "stop"}),
        rc("aws_eip.public", {"domain": "vpc"}),
        rc("aws_route53_record.staging", {"name": "staging.example.invalid", "type": "A"}, tagged=False),
    ]
    fx["plan-unsafe-unexpected-resources.json"] = plan(unexp)
    # a delete sneaking into an update
    dele = with_actions(base, ("no-op",))
    dele = [c if c["address"] != "aws_s3_bucket.staging" else with_actions([c], ("delete",))[0] for c in dele]
    fx["plan-unsafe-delete-in-update.json"] = plan(dele, prior=as_state(base))
    # weakened settings: IMDSv1, unencrypted volumes, public bucket, open egress, missing ExpiresAt
    weak = copy.deepcopy(base)
    for c in weak:
        a = c["change"]["after"]
        if c["address"] == "aws_instance.host":
            a["metadata_options"][0]["http_tokens"] = "optional"
            a["root_block_device"][0]["encrypted"] = False
            a["instance_initiated_shutdown_behavior"] = "stop"
        if c["address"] == "aws_ebs_volume.data":
            a["encrypted"] = False
        if c["address"] == "aws_s3_bucket_public_access_block.staging":
            a["restrict_public_buckets"] = False
        if c["address"] == "aws_vpc_security_group_egress_rule.https":
            a.update(ip_protocol="-1", from_port=None, to_port=None)
        if c["address"] == "aws_vpc.stg":
            a["tags_all"].pop("ExpiresAt")
    fx["plan-unsafe-weakened-settings.json"] = plan(weak)
    # a create against a root that already holds state
    fx["plan-unsafe-create-over-state.json"] = plan(base, prior=as_state(base))
    for name, doc in fx.items():
        with open(os.path.join(OUT, name), "w") as fh:
            json.dump(doc, fh, indent=1, sort_keys=True)
            fh.write("\n")
        print(name)


if __name__ == "__main__":
    main()
