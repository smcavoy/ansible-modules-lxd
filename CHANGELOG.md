# smcavoy\.lxd Release Notes

**Topics**

- <a href="#v0-1-3">v0\.1\.3</a>
    - <a href="#security-fixes">Security Fixes</a>
    - <a href="#bugfixes">Bugfixes</a>
- <a href="#v0-1-2">v0\.1\.2</a>
    - <a href="#release-summary">Release Summary</a>
    - <a href="#bugfixes-1">Bugfixes</a>
- <a href="#v0-1-1">v0\.1\.1</a>
    - <a href="#release-summary-1">Release Summary</a>
    - <a href="#security-fixes-1">Security Fixes</a>
    - <a href="#bugfixes-2">Bugfixes</a>
- <a href="#v0-1-0">v0\.1\.0</a>
    - <a href="#release-summary-2">Release Summary</a>
    - <a href="#bugfixes-3">Bugfixes</a>
    - <a href="#new-modules">New Modules</a>

<a id="v0-1-3"></a>
## v0\.1\.3

<a id="security-fixes"></a>
### Security Fixes

* lxd\_server\_config\, lxd\_server\_info \- the modules now mask the password in the URL of <code>core\.proxy\_http</code> and <code>core\.proxy\_https</code> in the result and the diff\, for example <code>http\://user\:\*\*\*\*\*\*\*\*\@proxy\:3128</code>\. The user\, the host\, and the port stay\. <code>lxd\_server\_config</code> also names the password of the task to Ansible as a secret\, and still compares the real values\. Before\, the password was in the output\.

<a id="bugfixes"></a>
### Bugfixes

* lxd\_cluster \- a boolean <code>value</code> in <code>join\_config</code> now goes to LXD as <code>\"true\"</code> or <code>\"false\"</code>\. Before\, <code>true</code> went as <code>\"True\"</code> and <code>false</code> as an empty string\.
* lxd\_cluster\_group \- <code>state\=absent</code> on a group that is in use \(its <code>used\_by</code> is not empty\, for example a project with <code>restricted\.cluster\.groups</code> or an instance placed with <code>target\=\@group</code>\) now fails before any change\, and the message names the users\. Before\, the module removed the members of the group\, and then LXD 6\.10\.1 refused the delete with <code>Cluster group is currently in use</code>\.
* lxd\_instance \- <code>state\=restarted</code> on a frozen instance now restarts it\. Before\, the module only sent <code>unfreeze</code> and reported a restart that did not happen\. LXD 6\.10\.1 refuses the restart of a frozen instance\, so the module sends <code>unfreeze</code> and then <code>restart</code>\.
* lxd\_instance\_file\, lxd\_instance\_exec \- an error on the read of a path \(the <code>HEAD</code> request\, also for <code>creates</code> and <code>removes</code>\) now has the message of LXD\, for example <code>not a directory</code>\. Before\, the message was only <code>HTTP 500</code>\, because the answer to a <code>HEAD</code> has no body\. The client reads the error text with a <code>GET</code> of the same path\, and does not read a file for it\.
* lxd\_instance\_info \- <code>all\_projects</code> now works with <code>name</code>\: the module returns the instances of that name from all projects\. Before\, it returned only the instance of the default project\.
* lxd\_network\_forward \- the module now compares <code>config\.target\_address</code> in the canonical form that LXD stores \(<code>fd42\:\:10</code> for <code>FD42\:0\:\:0010</code>\)\. Before\, another spelling of the address reported a change on every run\.
* lxd\_network\_forward \- the module now refuses the unspecified address \(<code>0\.0\.0\.0</code> or <code>\:\:</code>\) before it sends a request\. As <code>listen\_address</code>\, LXD reads it as a request to allocate an address\, so the forward does not get the address of the task\. As <code>config\.target\_address</code> or the <code>target\_address</code> of a port\, LXD refuses it\.
* lxd\_storage\_volume\_info \- on a cluster\, <code>include\_state</code> now asks the member that holds each volume \(its <code>location</code>\) for the state\. Before\, the state request used the <code>target</code> of the task\, or no member\.
* lxd\_storage\_volume\_snapshot \- <code>target</code> on a server that is not a cluster now fails with <code>target is only valid on a clustered server</code>\, as in <code>lxd\_storage\_volume</code>\. Before\, LXD answered <code>Cluster member not found</code>\, which the module read as a snapshot that does not exist\.

<a id="v0-1-2"></a>
## v0\.1\.2

<a id="release-summary"></a>
### Release Summary

A bugfix release\. <code>lxd\_network</code> and <code>lxd\_storage\_pool</code> now fail on a network or a pool whose cluster create did not finish \(the status <code>Pending</code> or <code>Errored</code>\)\. Before\, they reported <code>ok</code> for an object that LXD cannot use\. Tested against LXD 6\.10\.1\.

<a id="bugfixes-1"></a>
### Bugfixes

* lxd\_network\, lxd\_storage\_pool \- a network or a pool whose cluster create did not finish now fails the task\. LXD 6\.10\.1 leaves such an object with the status <code>Pending</code> \(the create stopped after the member step\) or <code>Errored</code> \(the cluster step failed\)\, and cannot use it\. Before\, the modules reported <code>ok</code>\. The message names the status and the members\, and says to remove the object with <code>state\=absent</code> and run the task again\.

<a id="v0-1-1"></a>
## v0\.1\.1

<a id="release-summary-1"></a>
### Release Summary

A bugfix release\. It has the fixes of a code review and the fix for file writes on a full disk\. Two tasks that reported a change on every run now fail with a clear message\, because LXD cannot do what they ask\: <code>lxd\_instance\_file</code> for a directory that exists with another owner or mode\, and <code>lxd\_image</code> with <code>expires\_at\=\"\"</code> on an image that has an expiry date\. Tested against LXD 6\.10\.1\.

<a id="security-fixes-1"></a>
### Security Fixes

* lxd\_network\, lxd\_network\_info \- the modules now mask the BGP peer passwords \(<code>bgp\.peers\.\<name\>\.password</code>\) in the result and the diff\. Before\, the password was in the output of the task\.
* lxd\_storage\_pool\, lxd\_storage\_pool\_info \- the modules now mask the secrets of the remote storage drivers \(<code>alletra\.user\.password</code>\, <code>powerflex\.user\.password</code>\, <code>powerstore\.user\.password</code>\, <code>pure\.api\.token</code>\) in the result and the diff\.

<a id="bugfixes-2"></a>
### Bugfixes

* lxd\_auth\_group \- a permission URL of an entity in the default project without <code>\?project\=default</code> no longer reports a change on every run\.
* lxd\_auth\_identity\_token \- an expired token no longer counts as a token\. LXD 6\.10\.1 keeps the type of the identity after the expiry time\, so the module reported <code>ok</code> and the client stayed locked out\. The module now reads <code>expires\_at</code> and issues a new token\.
* lxd\_cluster\_member \- <code>evacuate\_mode\=auto</code> now sends no mode\, so that LXD chooses for each instance\. LXD 6\.10\.1 has no mode of that name and refused it when the member had an instance\.
* lxd\_cluster\_member \- the module now knows the automatic roles of LXD 6\.10\.1 \(<code>database\-voter</code>\, <code>database\-standby</code>\, <code>database\-leader</code>\)\. Before\, a task with <code>roles</code> reported a change on every run for a member with the role <code>database\-voter</code>\.
* lxd\_image \- <code>expires\_at\=\"\"</code> on an image with an expiry date now fails with a clear message\. LXD cannot remove the date\, and the module reported a change on every run\.
* lxd\_instance\_backup\, lxd\_storage\_volume\_backup\, lxd\_image\_export\, lxd\_instance\_file \- a download that the server cuts short is no longer taken as a complete file\. The client compares the size with <code>Content\-Length</code> and reads again\.
* lxd\_instance\_exec \- <code>removes</code> with an instance that does not exist now fails\. Before\, the task reported <code>ok</code> as if the path did not exist\.
* lxd\_instance\_file \- a link with a relative target is now idempotent\, and a new target replaces a link that exists\. Before\, the first reported a change on every run and the second failed with \"file exists\"\.
* lxd\_instance\_file \- a write on a full disk no longer leaves a wrong file behind without a word\. LXD 6\.10\.1 creates or empties the file before it writes\, and on a full btrfs pool it can answer a small write with success and store nothing\. The module now reads the file back after each write and fails when the content differs\. After a failed write it deletes a new file\, or tries to write the old content back and says whether that worked\.
* lxd\_instance\_file \- the module fails with a clear message when a directory exists with another owner or mode\. LXD cannot change them\, and the module reported a change on every run\. A mode with the setuid\, setgid or sticky bit is refused for the same reason\.
* lxd\_instance\_rebuild\, lxd\_instance\_device \- a frozen instance\, and an instance with the status <code>Ready</code>\, now count as running\. <code>force</code> and <code>allow\_restart</code> stop them as they stop a running instance\.
* lxd\_instance\_snapshot\, lxd\_storage\_volume\_snapshot \- <code>expires\_at\=\"\"</code> on a new snapshot now makes a snapshot that never expires\. Before\, LXD used <code>snapshots\.expiry</code> of the instance or the volume\, and a second run was necessary\.
* lxd\_network\, lxd\_storage\_pool \- a change of a member\-specific key on a cluster \(<code>member\_config</code>\) no longer removes the global config of the network or the pool\. LXD 6\.10\.1 replaces the whole config on a <code>PUT</code> with a target\, and the module sent only the member\-specific keys\.
* lxd\_network\_acl\, lxd\_network\_forward\, lxd\_network\_load\_balancer \- values that LXD stores in another form no longer report a change on every run\: spaces in the lists of addresses and ports\, and IP addresses that are not in the canonical form\. An upper\-case IPv6 <code>listen\_address</code> no longer fails on the second run\.
* lxd\_storage\_volume\_info \- <code>include\_state\=true</code> no longer fails on a pool that holds an image volume\. LXD has a state only for custom\, container and virtual\-machine volumes\. For other volumes <code>state</code> is null\.

<a id="v0-1-0"></a>
## v0\.1\.0

<a id="release-summary-2"></a>
### Release Summary

The first release of <code>smcavoy\.lxd</code>\: 63 modules for the LXD 6\.10 REST API\, with no Python dependency outside ansible\-core\. Tested against LXD 6\.10\.1 on standalone servers\, clusters\, linked clusters and MicroCloud \(OVN and Ceph\)\, on ansible\-core 2\.19 to 2\.22 and Python 3\.11 to 3\.13\.

<a id="bugfixes-3"></a>
### Bugfixes

* all modules \- <code>state\=absent</code> with a project that does not exist now fails and names the project\, instead of reporting the object as absent\. A missing parent object gives a warning\.
* all modules \- a connection error\, such as a wrong <code>server\_fingerprint</code>\, now shows its text and not a Python tuple\.
* all modules \- an LXD operation longer than 60 seconds no longer fails with <code>context deadline exceeded</code>\. The wait goes on until <code>timeout</code>\, also through short connection breaks\, and a timeout says that the operation can still run\.
* all modules \- check mode no longer uses up a one\-time <code>trust\_token</code>\.
* all modules \- the wait for an operation now goes on while LXD restarts\. Before\, the HTTP 500 that LXD sends during its shutdown \(<code>sql\: database is closed</code>\) failed the task at once\.
* all modules \- the wait for an operation now keeps to <code>timeout</code> when the connection to LXD hangs\. Before\, each read retry waited a full socket timeout\, so a 40 second timeout could run more than 2 minutes\.
* all modules \- when LXD no longer knows an operation after a connection break\, the error now says that the operation can have finished during the break and that its result is unknown\.
* all modules \- when two runs create the same object at the same time\, the second run no longer fails with <code>already exists</code>\. It reads the object again once and updates it if needed\.
* lxd\_instance\_backup\, lxd\_storage\_volume\_backup\, lxd\_image\_export\, lxd\_image \- backups and images are now streamed to and from disk in 1 MiB chunks\, not held whole in controller memory\. A download broken by a connection reset starts the file again\.
* lxd\_instance\_exec \- when LXD restarts or the connection breaks during the command\, the error now says that the command can still run in the instance\, or that it ran\, and that a new run of the task runs it again\. Before\, it said to run the task again\.
* lxd\_instance\_file \- <code>owner\_uid</code>\, <code>owner\_gid</code> and <code>mode</code> now keep the values of an existing path when the task does not set them\. Before\, a task that set only <code>content</code> changed the file to root and <code>0644</code>\.
* lxd\_instance\_file \- a file that root in the instance does not own and that gives no write to others \(for example <code>0600</code> owned by uid 1000\) can now be changed\. LXD refuses that overwrite with 403\, so the module deletes the file and writes it again\. The inode changes\, so hard links to the file break\.
* lxd\_instance\_file \- files are now streamed\. The file in the instance is read into a temporary file for the SHA\-256 compare\, and uploads \(of <code>src</code>\, and a write again for an owner or mode change\) stream from disk\, so a large file does not need controller memory\.

<a id="new-modules"></a>
### New Modules

* smcavoy\.lxd\.lxd\_auth\_group \- Manage LXD authorization groups\.
* smcavoy\.lxd\.lxd\_auth\_identity \- Manage LXD TLS\, bearer\, and OIDC identities\.
* smcavoy\.lxd\.lxd\_auth\_identity\_provider\_group \- Map identity provider groups to LXD groups\.
* smcavoy\.lxd\.lxd\_auth\_identity\_token \- Issue and revoke tokens of LXD bearer identities\.
* smcavoy\.lxd\.lxd\_auth\_info \- Read LXD access control\.
* smcavoy\.lxd\.lxd\_cluster \- Form an LXD cluster\, join it\, or remove a member\.
* smcavoy\.lxd\.lxd\_cluster\_certificate \- Replace the certificate of an LXD cluster\.
* smcavoy\.lxd\.lxd\_cluster\_group \- Manage LXD cluster groups\.
* smcavoy\.lxd\.lxd\_cluster\_join\_token \- Issue and revoke LXD cluster join tokens\.
* smcavoy\.lxd\.lxd\_cluster\_link \- Manage links between LXD clusters\.
* smcavoy\.lxd\.lxd\_cluster\_link\_info \- Read LXD cluster links\.
* smcavoy\.lxd\.lxd\_cluster\_member \- Manage LXD cluster members\.
* smcavoy\.lxd\.lxd\_cluster\_member\_info \- Read LXD cluster members\.
* smcavoy\.lxd\.lxd\_image \- Manage LXD images\.
* smcavoy\.lxd\.lxd\_image\_alias \- Manage LXD image aliases\.
* smcavoy\.lxd\.lxd\_image\_export \- Download an LXD image to the controller\.
* smcavoy\.lxd\.lxd\_image\_info \- Read LXD images\.
* smcavoy\.lxd\.lxd\_image\_registry \- Manage LXD image registries\.
* smcavoy\.lxd\.lxd\_image\_registry\_info \- Read LXD image registries\.
* smcavoy\.lxd\.lxd\_instance \- Manage LXD containers and virtual machines\.
* smcavoy\.lxd\.lxd\_instance\_backup \- Manage LXD instance backups\.
* smcavoy\.lxd\.lxd\_instance\_device \- Manage one device of an LXD instance\.
* smcavoy\.lxd\.lxd\_instance\_exec \- Run a command in an LXD instance\.
* smcavoy\.lxd\.lxd\_instance\_file \- Manage files\, directories\, and symlinks in LXD instances\.
* smcavoy\.lxd\.lxd\_instance\_info \- Read LXD instances\.
* smcavoy\.lxd\.lxd\_instance\_log\_info \- Read the log files of an LXD instance\.
* smcavoy\.lxd\.lxd\_instance\_metadata \- Manage the metadata and templates of an LXD instance\.
* smcavoy\.lxd\.lxd\_instance\_rebuild \- Rebuild the root disk of an LXD instance\.
* smcavoy\.lxd\.lxd\_instance\_snapshot \- Manage LXD instance snapshots\.
* smcavoy\.lxd\.lxd\_network \- Manage LXD networks\.
* smcavoy\.lxd\.lxd\_network\_acl \- Manage LXD network ACLs\.
* smcavoy\.lxd\.lxd\_network\_acl\_info \- Read LXD network ACLs\.
* smcavoy\.lxd\.lxd\_network\_allocation\_info \- Read the addresses that LXD networks use\.
* smcavoy\.lxd\.lxd\_network\_forward \- Manage LXD network forwards\.
* smcavoy\.lxd\.lxd\_network\_info \- Read LXD networks\.
* smcavoy\.lxd\.lxd\_network\_load\_balancer \- Manage LXD OVN load balancers\.
* smcavoy\.lxd\.lxd\_network\_load\_balancer\_pool \- Manage LXD OVN load balancer pools\.
* smcavoy\.lxd\.lxd\_network\_peer \- Manage peers between LXD OVN networks\.
* smcavoy\.lxd\.lxd\_network\_zone \- Manage LXD network zones\.
* smcavoy\.lxd\.lxd\_network\_zone\_record \- Manage records in LXD network zones\.
* smcavoy\.lxd\.lxd\_operation\_info \- Read LXD operations\.
* smcavoy\.lxd\.lxd\_placement\_group \- Manage LXD placement groups\.
* smcavoy\.lxd\.lxd\_profile \- Manage LXD profiles\.
* smcavoy\.lxd\.lxd\_profile\_info \- Read LXD profiles\.
* smcavoy\.lxd\.lxd\_project \- Manage LXD projects\.
* smcavoy\.lxd\.lxd\_project\_info \- Read LXD projects\.
* smcavoy\.lxd\.lxd\_replicator \- Manage LXD replicators\.
* smcavoy\.lxd\.lxd\_replicator\_info \- Read LXD replicators\.
* smcavoy\.lxd\.lxd\_replicator\_run \- Run an LXD replicator\.
* smcavoy\.lxd\.lxd\_server\_config \- Manage the LXD server config\.
* smcavoy\.lxd\.lxd\_server\_info \- Read LXD server information\.
* smcavoy\.lxd\.lxd\_storage\_bucket \- Manage LXD storage buckets\.
* smcavoy\.lxd\.lxd\_storage\_bucket\_key \- Manage access keys of LXD storage buckets\.
* smcavoy\.lxd\.lxd\_storage\_pool \- Manage LXD storage pools\.
* smcavoy\.lxd\.lxd\_storage\_pool\_info \- Read LXD storage pools\.
* smcavoy\.lxd\.lxd\_storage\_volume \- Manage LXD custom storage volumes\.
* smcavoy\.lxd\.lxd\_storage\_volume\_backup \- Manage backups of LXD custom storage volumes\.
* smcavoy\.lxd\.lxd\_storage\_volume\_info \- Read LXD storage volumes\.
* smcavoy\.lxd\.lxd\_storage\_volume\_snapshot \- Manage snapshots of LXD custom storage volumes\.
* smcavoy\.lxd\.lxd\_trust\_certificate \- Manage certificates in the LXD trust store\.
* smcavoy\.lxd\.lxd\_trust\_token \- Issue and revoke LXD trust tokens\.
* smcavoy\.lxd\.lxd\_warning \- Acknowledge or delete LXD warnings\.
* smcavoy\.lxd\.lxd\_warning\_info \- Read LXD warnings\.
