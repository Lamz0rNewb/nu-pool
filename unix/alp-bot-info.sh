##########################################################################################
#
#!/bin/bash
# version 0.30 - changed names
#	from	[pool]-[exchange]-[pair]
#	to	[pool]_[exchange]_[pair]
#
# version 0.40 - moved script to unix directory
#	and adjusted paths accordingly
#
# version 0.41 - changed name to make auto completion in bash more convenient
#
# version 0.42 - changed output to improve the readability
#
# version 0.45 - added nupond_bter_cny_fix_payout_test
#
# version 0.50 - prepared southxchange ("southx") bots
#
# version 0.55 - moved fixed cost pool nupond_bter_cny_fix_payout_test to
#               nupond_bter_btc_fix_payout_test
#
# version 0.60 - simplified the script by using an array for the pools
#
#
##########################################################################################

##########################################################################################

# This is another nastily scripted, but hopefully helpful tool
# to quickly check the status of multiple ALP bots.
#
# The first line of output print the current date and time
# This is useful to verify the last messages in the logs that will be
# listed right after
#
# The standard output per ALP bot is
#	### pool name ###
# 	full path to most recent log - makes digging in this particular log easy
#	second last line of the log
#	last line of the log 
#
# If that output is not after your fancy, just edit it.
# It was just a try. I ended up with this type of check, because I find it convenient :)
#
##########################################################################################


# Some variables - additional ALP bots might be appended following the same style
cwd=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )

alp_bot_array=(
liquidbits_ccedk_btc
liquidbits_ccedk_eur
liquidbits_ccedk_usd
liquidbits_southx_usd
liquidbits_southx_btc
nupond_bter_btc
nupond_bter_cny
nupool_bittrex_btc
nupool_poloniex_btc
nuriver_cryptsy_btc
nuriver_cryptsy_usd )

n=0

date

for bot in "${alp_bot_array[@]}"
do
	poolname="${alp_bot_array[$n]}"
#	echo $poolname
	poollogdir=$cwd/$poolname/logs/
#	echo $poollogdir
	if [ -d $poollogdir ]; then
        	poollog=`ls -t $poollogdir | head -n 1`
#		echo $poollog
		echo "### $poolname ###"
		echo $poollogdir$poollog
		tail -n 10 $poollogdir$poollog | sort -r | grep ask | head -n 1 && echo
	fi
	((n++))
done
