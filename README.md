# AniList AMQ Tool

A tool for modifying and generating AniList lists.

# Disclaimer

Don't be surprised if there are bugs/weirdness/undocumented behaviour. I wrote this script in 2 days.

Don't use a token from an important AniList account - I make no quarantees your anime list won't be accidentally wiped due to some error

`media` in the documentation and code just refers to anime entries in AniList. This from the terminology used in the AniList GraphQL schemas.

# Setup
You probably want to set up a virtual python environment to install
the dependencies into On linux you would do this by running something
along the following lines:

```
python3.11 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
```
On Windows, the commands differ a bit - do your own research

# Something

The script can chain various commands to fetch, filter and edit AniList lists.

* Some commands can fetch/load `media` to a named `media set`s
    * Basically you can load entries from your, or some  other users AniList
* Some commands can filter named `media set`s and store results to other named `media set`s
    * Mainly the `sample_set` command
* Some commands can add/update your AniList list based on a named `media set`
    * `update_or_add_media` and `replace_list` commands
* The `ALL` media set contains all animes, as long as you have downloaded them locally using `update_data`

# Sampling

`sample_set` command is the function used to filter and generate `media set`s (anime lists). `sample_set` takes 2 positional arguments - a named source `media set` and a target `media set`. Additionally, you can define size of the sample, as well as various filters. Check `./anilist-amq-tool.py --no-data sample_set --help` to list all sampling options

If you define `--seed <number>` for the `sample_set` command, the results should be quite stable. Meaning that you should get almost same results every time, even if the source set slightly changes.

`--offset` can be used to offset the generated list. E.g. If you generate 2 sets with `--size 10, --offset 0` and `--size 10 --offset 5`, The latter should have 5 animes in common with the first set, and 5 new ones.


# Examples

**Print a random anime selection**
* Generate 2 random sets of anime (A and B) within the given
  constraints
* Print the sets in an easy-to-read text format:
```
./anilist-amq-tool.py
        sample_set ALL A --max-popularity-percent 10 - \
        sample_set ALL B ---min-year 2022 --genres scifi,fantasy - \
        print A --text - \
        print B --text - \
        end
```

**Generate a random AniList list**
* Generate 2 random sets of anime (A and B) within the given
  constraints
* Add the sets to your anime list.
  * Set A as "PLANNING"
  * Set B as "COMPLETED"
* Access token to needed to access your account is read from the
  file `token.txt`
```
set B as "COMPLETED"
./anilist-amq-tool.py -a "$(cat token.txt)" \
        sample_set ALL A --max-popularity-percent 10 - \
        sample_set ALL B ---min-year 2022 --genres scifi,fantasy - \
        update_or_add_media A --status PLANNING - \
        update_or_add_media B --status COMPLETE - \
        end
```

**Generate an AniList list based on another users's list**
* Fetch anime list of the AniList user `another_user`
* Randomly select 20 animes from that list
* Replace your list (user authenticated with the given token)
  with the selected animes
```
set B as "COMPLETED"
./anilist-amq-tool.py -a "$(cat token.txt)" \
        fetch_user_media A --username `another_user` \
        sample_set A B --max-popularity-percent 10 --size 10 --seed 1 - \
        update_or_add_media B --status COMPLETED - \
        end
```

# Chaining commands
In general, you can chain commands as
```
./anilist-amq-tool.py <common options> \
        <command 1> <args 1> <options 1> - \
        <command 2> <args 2> <options 2> - \
        <...> - \
        end`
```
* `args` are positional arguments
* `option` refers to options starting with with `-` or `--`.
* The `media set` `ALL` contains all animes, as long as you have downloaded them locally using the `update_dat` command
* Run `./anilist-amq-tool.py --no-data` to see all available commands
* Run `./anilist-amq-tool.py --help` to see the available `common options`
* Run `./anilist-amq-tool.py --no-data <command> --help` to see what each individual command does
* `--no-data` just means the script does not try to load all animes from a file
* `-` indicates there are no more arguments for the previous command in the chain

The command line interface is constructed automatically using the `fire`
library
