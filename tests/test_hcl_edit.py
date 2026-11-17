"""
G16 (Break-It Lab run 2): a fix PR edits only the one resource block.

Lab PR #1 replaced a 189-line aws/main.tf with a malformed 33-line JSON dump
of one security group. The fixture below has the same shape as a real stack:
several resources, a heredoc, comments, interpolations with braces inside
strings.
"""
import pytest

from core.hcl_edit import (
    HclEditError, replace_resource_block, resource_addresses, resource_block_text,
    top_level_blocks, unified_diff,
)

STACK = '''terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

variable "enable_ssh" {
  type    = bool
  default = false # flip for the lab scenario
}

# Web tier security group. A "}" in this comment must not close anything.
resource "aws_security_group" "web" {
  name        = "cdlab-web"
  description = "web ${var.enable_ssh ? "with" : "without"} ssh {braces in a string}"

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "app" {
  ami           = data.aws_ami.al2023.id
  instance_type = "t3.micro"
  user_data     = <<-EOF
    #!/bin/bash
    echo "{ not hcl }" > /tmp/x
    }
  EOF
  /* tags { are here } */
  tags = { Name = "cdlab-app", lab = "cloud-decoded" }
}

output "sg_id" { value = aws_security_group.web.id }
'''

FIXED_SG = '''resource "aws_security_group" "web" {
  name        = "cdlab-web"
  description = "web ${var.enable_ssh ? "with" : "without"} ssh {braces in a string}"

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}'''

LAB_JSON = '{"aws_security_group": {"web": {"name": "cdlab-web", "ingress": [{"from_port": 443'


def test_finds_every_top_level_block_and_ignores_braces_in_strings_comments_heredocs():
    kinds = [(b.kind, b.labels) for b in top_level_blocks(STACK)]
    assert kinds == [
        ("terraform", ()), ("variable", ("enable_ssh",)),
        ("resource", ("aws_security_group", "web")), ("resource", ("aws_instance", "app")),
        ("output", ("sg_id",)),
    ]
    assert resource_addresses(STACK) == ["aws_security_group.web", "aws_instance.app"]


def test_lab_a2_fix_changes_only_the_security_group():
    after = replace_resource_block(STACK, "aws_security_group.web", FIXED_SG)
    before_sg = resource_block_text(STACK, "aws_security_group.web")
    # everything outside the block is byte-identical
    assert after.replace(FIXED_SG + "\n", "") == STACK.replace(before_sg, "")
    assert 'resource "aws_instance" "app"' in after and "terraform {" in after
    diff = unified_diff("aws/main.tf", STACK, after)
    removed = [l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
    added = [l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    assert added == []
    assert "from_port   = 22" in "\n".join(removed) and len(removed) == 7


def test_replacing_a_block_with_itself_is_a_no_op():
    for address in resource_addresses(STACK):
        assert replace_resource_block(STACK, address, resource_block_text(STACK, address)) == STACK


@pytest.mark.parametrize("proposed,reason", [
    (LAB_JSON + "}]}}}", "JSON"),                                     # lab PR #1/#2
    ("", "empty"),
    (FIXED_SG + "\n" + FIXED_SG, "exactly one"),
    (FIXED_SG.replace('"web"', '"web2"'), "not aws_security_group.web"),
    (FIXED_SG[:-1], "never closes"),                                  # unbalanced
    (FIXED_SG + '\nresource_count = 1', "outside the resource block"),
    ('variable "x" {}', "not aws_security_group.web"),
])
def test_unsafe_proposals_are_refused(proposed, reason):
    with pytest.raises(HclEditError, match=reason):
        replace_resource_block(STACK, "aws_security_group.web", proposed)


def test_address_must_exist_exactly_once():
    with pytest.raises(HclEditError, match="not defined"):
        replace_resource_block(STACK, "aws_security_group.db", FIXED_SG.replace('"web"', '"db"'))
    doubled = STACK + "\n" + resource_block_text(STACK, "aws_security_group.web")
    with pytest.raises(HclEditError, match="more than once"):
        replace_resource_block(doubled, "aws_security_group.web", FIXED_SG)


@pytest.mark.parametrize("bad", ["sg-0abc123", "aws_security_group", "", "a.b.c"])
def test_address_must_be_type_dot_name(bad):
    with pytest.raises(HclEditError):
        replace_resource_block(STACK, bad, FIXED_SG)


def test_comment_after_proposed_block_is_allowed():
    after = replace_resource_block(STACK, "aws_security_group.web", FIXED_SG + "  # closed :22")
    assert "# closed :22" in after


@pytest.mark.parametrize("broken", ['resource "a" "b" {\n  x = "unterminated\n}\n',
                                    'resource "a" "b" {\n  y = <<EOF\nnever ends\n}\n',
                                    'resource "a" "b" {\n}\n}\n'])
def test_malformed_files_raise_instead_of_guessing(broken):
    with pytest.raises(HclEditError):
        top_level_blocks(broken)
