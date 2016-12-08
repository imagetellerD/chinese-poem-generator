from fabric.api import local, lcd, put, get
from fabric.api import env
import os

env.hosts=['username@host:port']
env.password = 'remotepasswd if necessary'

base_dir = 'your_remote_path'

def git_status():
	local('git branch')
	local('git status')

def git_commit(branch="develop", m="update"):
	try:
		local('git add -A')
		local('git commit -m "%s"' % m)
	except:
		print 'Git add already' 
	finally:
		local('git push origin %s' % branch)

def scp_from_remote(*files):
	cur_dir = os.getcwd()
	for file in files:
		total_file_path = file.rsplit('/', 1)
		if len(total_file_path) > 1:
			file_path, file_name = total_file_path[0], total_file_path[1]
		else:
			file_path, file_name = '', total_file_path[0]
		get(os.path.join(base_dir, file), os.path.join(cur_dir, file_path))
	#[ get(os.path.join(base_dir, file), file) for file in files ]

def scp_to_remote(*files):
	for file in files:
		total_file_path = file.rsplit('/', 1)
		if len(total_file_path) > 1:
			file_path, file_name = total_file_path[0], total_file_path[1]
		else:
			file_path, file_name = '', total_file_path[0]
		put(file, os.path.join(base_dir, file_path))
	#[ put(file, os.path.join(base_dir, file)) for file in files ]
