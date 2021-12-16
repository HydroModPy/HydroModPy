=======================================
Default home directory creation process
=======================================

Normal home directories in rocks work like this:

* /usr/sbin/useradd creates the home directory in /export/home/$USER (based on the settings in /etc/default/useradd)
* rocks sync users adjusts all home directories that are listed as /export/home as follows:

 * edit /etc/password, replacing /export/home/ with /home/
 * add a line to /etc/auto.home pointing to the existing directory in /export/home
 * 411 is updated, to propagate the changes in /etc/passwd and /etc/auto.home

In the default Rocks configuration, /home/ is an automount directory. By default, directories in an automount directory are not present until an attempt is made to access them, at which point they are (usually NFS) mounted. This means you CANNOT create a directory in /home/ manually! The contents of /home/ are under autofs control. To "see" the directory, it's not enough to do a ls /home as that only accesses the /home directory itself, not its contents. To see the contents, you must ls /home/username.


Changing the default
====================

Placing user home directories on an external NAS (Rocks 5.4 or greater)
------------------------------------------------------------------------

If you want to place all your home directory on an external NAS you can do the following:

- mount the NFS share onto /export/home on your FE
- leave /export/home as the default dir in /etc/default/useradd
- rocks set attr Info_HomeDirSrv "my-server-name" (where my-server-name is the NAS internal hostname)
- rocks set attr Info_HomeDirLoc "/home-path-on-nfs-server"

Info_HomeDirSrv and Info_HomeDirLoc will be used to compose the user line in /etc/auto.home every time a new user is added and the rocks sync users command is run. Since Rocks 6.0 you can use the Info_HomeDirOptions to set the mount options.


Relocate user home directories
------------------------------

Here's an overview of what to do to move a user's home directory:

* Relocate the user's actual directory (using tar, cpio, rsync, mv, or whatever) to the new location if it isn't already there.
* edit /etc/auto.home to point to that new location
* update 411: (cd /var/411; make)

If for some reason it is desirable to have home directories on multiple servers, all that is necessary is to make sure all the nodes in the cluster can mount the directories from the servers (i.e., they are exported correctly), and then edit /etc/auto.home to reflect the real location of each home directory.

