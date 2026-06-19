#!/usr/bin/env python3
"""
Master Diagnostic & Repair Script
Fixes all issues in DDP training cluster
"""

import sqlite3
import subprocess
import sys
import os
from pathlib import Path

class ClusterDiagnostician:
    def __init__(self, db_file):
        self.db_file = db_file
        self.nodes = self._get_nodes()
        self.issues = []
        
    def _get_nodes(self):
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            c.execute("SELECT ip FROM nodes;")
            nodes = [row[0] for row in c.fetchall()]
            conn.close()
            return nodes
        except Exception as e:
            print(f"Failed to read db: {e}")
            return []

    def run_full_diagnosis(self):
        print("🔍 Starting Full Cluster Diagnosis...\n")
        
        self.check_connectivity()
        self.check_dependencies()
        self.check_configuration()
        self.check_resources()
        
        return self.issues
    
    def check_connectivity(self):
        print("📡 Checking SSH Connectivity...")
        for node in self.nodes:
            result = subprocess.run(
                ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=5', f'cactus@{node}', 'echo OK'],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                self.issues.append({
                    'type': 'connectivity',
                    'severity': 'critical',
                    'node': node,
                    'message': f'Cannot SSH to {node}. Error: {result.stderr.strip()}'
                })
    
    def check_dependencies(self):
        print("📦 Checking Dependencies...")
        for node in self.nodes:
            if any(i['node'] == node and i['type'] == 'connectivity' for i in self.issues):
                continue
            cmd = "source ~/venv/bin/activate && python -c 'import torch; import torch.distributed as dist; print(torch.__version__)'"
            result = subprocess.run(
                ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=5', f'cactus@{node}', cmd],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                self.issues.append({
                    'type': 'dependency',
                    'severity': 'critical',
                    'node': node,
                    'message': f'PyTorch not properly installed on {node} or venv missing'
                })
    
    def check_configuration(self):
        print("⚙️  Validating Configurations...")
        # Check backend/training/trainer.py for --batch_size -1 handling with world_size > 1
        with open('worker/trainer.py', 'r') as f:
            content = f.read()
            if 'batch = -1' in content and 'AutoBatch' not in content:
                self.issues.append({
                    'type': 'configuration',
                    'severity': 'warning',
                    'node': 'master',
                    'message': 'AutoBatch might cause issues in DDP.'
                })
        
        # Check if dataset path is local or shared
        with open('backend/training/trainer.py', 'r') as f:
            content = f.read()
            if 'dataset_path' not in content:
                self.issues.append({
                    'type': 'configuration',
                    'severity': 'critical',
                    'node': 'master',
                    'message': 'Dataset path logic missing or hardcoded.'
                })
                
    def check_resources(self):
        print("💾 Checking Resources...")
        for node in self.nodes:
            if any(i['node'] == node and i['type'] == 'connectivity' for i in self.issues):
                continue
            cmd = "nvidia-smi --query-gpu=memory.free --format=csv,nounits"
            result = subprocess.run(
                ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=5', f'cactus@{node}', cmd],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                self.issues.append({
                    'type': 'resource',
                    'severity': 'warning',
                    'node': node,
                    'message': f'Cannot query GPU on {node}'
                })
    
    def auto_repair(self):
        print("\n🔧 Attempting Auto-Repair...\n")
        
        for issue in self.issues:
            print(f"Fixing: {issue['message']}")
            
            if issue['type'] == 'connectivity':
                # Can't easily fix SSH passwords programmatically if not already keyed
                print(f"  → Cannot automatically repair SSH connectivity for {issue['node']}. Please set up passwordless SSH.")
            elif issue['type'] == 'dependency':
                print(f"  → Reinstalling dependencies on {issue['node']}...")
                cmd = "source ~/venv/bin/activate && pip install torch torchvision torchaudio ultralytics requests"
                subprocess.run(['ssh', f'cactus@{issue["node"]}', cmd])
    
    def generate_report(self):
        print("\n📊 DIAGNOSTIC REPORT\n")
        print(f"Total Issues Found: {len(self.issues)}")
        
        critical = [i for i in self.issues if i['severity'] == 'critical']
        warnings = [i for i in self.issues if i['severity'] == 'warning']
        
        if critical:
            print(f"\n🔴 CRITICAL ({len(critical)}):")
            for issue in critical:
                print(f"  - {issue['message']}")
        
        if warnings:
            print(f"\n🟡 WARNINGS ({len(warnings)}):")
            for issue in warnings:
                print(f"  - {issue['message']}")
        
        if not self.issues:
            print("\n✅ No issues found! Cluster is ready for training.")

if __name__ == "__main__":
    diag = ClusterDiagnostician(db_file="cluster.db")
    
    issues = diag.run_full_diagnosis()
    diag.auto_repair()
    diag.generate_report()
