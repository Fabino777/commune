# The MIT License (MIT)
# Copyright © 2021 Yuma Rao
# Copyright © 2023 Opentensor Foundation

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated 
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation 
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, 
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of 
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL 
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION 
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER 
# DEALINGS IN THE SOFTWARE.

# Imports
import torch
import scalecodec
from retry import retry
from typing import List, Dict, Union, Optional, Tuple
from substrateinterface import SubstrateInterface
from bittensor.utils.balance import Balance

from rich.prompt import Confirm
from commune.subspace.utils import U16_NORMALIZED_FLOAT, U64_MAX, RAOPERTAO, U16_MAX
from commune.subspace.utils import is_valid_address_or_public_key
from commune.subspace.chain_data import NeuronInfo, AxonInfo, DelegateInfo, PrometheusInfo, SubnetInfo, NeuronInfoLite
from commune.subspace.errors import ChainConnectionError, ChainTransactionError, ChainQueryError, StakeError, UnstakeError, TransferError, RegistrationError, SubspaceError

# Logging
from loguru import logger
logger = logger.opt(colors=True)

class Subspace:
    """
    Handles interactions with the subspace chain.
    """
    
    def __init__( 
        self, 
        network: str = 'local',
        url: str = '127.0.0.1:9944',
        **kwargs,
    ):
        r""" Initializes a subspace chain interface.
            Args:
                substrate (:obj:`SubstrateInterface`, `required`): 
                    substrate websocket client.
                network (default='local', type=str)
                    The subspace network flag. The likely choices are:
                            -- local (local running network)
                            -- nobunaga (staging network)
                            -- nakamoto (main network)
                    If this option is set it overloads subspace.chain_endpoint with 
                    an entry point node from that network.
                chain_endpoint (default=None, type=str)
                    The subspace endpoint flag. If set, overrides the network argument.
        """
        self.set_substrate( network=network, url=url)


    network2url_map = {
        'local': 'ws://127.0.0.1:9944'
        }
    @classmethod
    def network2url(cls, network:str) -> str:
        return cls.network2url_map.get(network, None)
    @classmethod
    def url2network(cls, url:str) -> str:
        return {v: k for k, v in cls.network2url_map.items()}.get(url, None)
    
    def set_substrate(self, 
                url:str="ws://127.0.0.1:9944", 
                network:str = None,
                websocket:str=None, 
                ss58_format:int=42, 
                type_registry:dict=__type_registery__, 
                type_registry_preset=None, 
                cache_region=None, 
                runtime_config=None, 
                use_remote_preset=False,
                ws_options=None, 
                auto_discover=True, 
                auto_reconnect=True, 

                *args, 
                **kwargs):

        '''
        A specialized class in interfacing with a Substrate node.

        Parameters
       A specialized class in interfacing with a Substrate node.

        Parameters
        url : the URL to the substrate node, either in format <https://127.0.0.1:9933> or wss://127.0.0.1:9944
        
        ss58_format : The address type which account IDs will be SS58-encoded to Substrate addresses. Defaults to 42, for Kusama the address type is 2
        
        type_registry : A dict containing the custom type registry in format: {'types': {'customType': 'u32'},..}
        
        type_registry_preset : The name of the predefined type registry shipped with the SCALE-codec, e.g. kusama
        
        cache_region : a Dogpile cache region as a central store for the metadata cache
        
        use_remote_preset : When True preset is downloaded from Github master, otherwise use files from local installed scalecodec package
        
        ws_options : dict of options to pass to the websocket-client create_connection function
        : dict of options to pass to the websocket-client create_connection function
                
        '''
        from substrateinterface import SubstrateInterface

        if url == None:
            assert network != None, "network or url must be set"
            url = self.network2url(network)
        if not url.startswith('ws://'):
            url = f'ws://{url}'
        
        if network == None:
            network = self.url2network(url)
        self.network = network 
        self.url = self.chain_endpoint = url
        
        
        
        self.substrate= SubstrateInterface(
                                    url=url, 
                                    websocket=websocket, 
                                    ss58_format=ss58_format, 
                                    type_registry=type_registry, 
                                    type_registry_preset=type_registry_preset, 
                                    cache_region=cache_region, 
                                    runtime_config=runtime_config, 
                                    use_remote_preset=use_remote_preset,
                                    ws_options=ws_options, 
                                    auto_discover=auto_discover, 
                                    auto_reconnect=auto_reconnect, 
                                    *args,
                                    **kwargs)
        
      

    def __repr__(self) -> str:
        return self.__str__()


    #####################
    #### Set Weights ####
    #####################
    def set_weights(
        self,
        netuid: int,
        uids: Union[torch.LongTensor, list] ,
        weights: Union[torch.FloatTensor, list],
        key: 'commune.key' = None,
        wait_for_inclusion:bool = False,
        wait_for_finalization:bool = False,
        prompt:bool = False
    ) -> bool:
        r""" Sets the given weights and values on chain for wallet hotkey account.
        Args:
            wallet (bittensor.wallet):
                bittensor wallet object.
            netuid (int):
                netuid of the subent to set weights for.
            uids (Union[torch.LongTensor, list]):
                uint64 uids of destination neurons.
            weights ( Union[torch.FloatTensor, list]):
                weights to set which must floats and correspond to the passed uids.
            version_key (int):
                version key of the validator.
            wait_for_inclusion (bool):
                if set, waits for the extrinsic to enter a block before returning true,
                or returns false if the extrinsic fails to enter the block within the timeout.
            wait_for_finalization (bool):
                if set, waits for the extrinsic to be finalized on the chain before returning true,
                or returns false if the extrinsic fails to be finalized within the timeout.
            prompt (bool):
                If true, the call waits for confirmation from the user before proceeding.
        Returns:
            success (bool):
                flag is true if extrinsic was finalized or uncluded in the block.
                If we did not wait for finalization / inclusion, the response is true.
        """
        # First convert types.
        if isinstance( uids, list ):
            uids = torch.tensor( uids, dtype = torch.int64 )
        if isinstance( weights, list ):
            weights = torch.tensor( weights, dtype = torch.float32 )

        # Reformat and normalize.
        weight_uids, weight_vals = weight_utils.convert_weights_and_uids_for_emit( uids, weights )

        # Ask before moving on.
        if prompt:
            if not Confirm.ask("Do you want to set weights:\n[bold white]  weights: {}\n  uids: {}[/bold white ]?".format( [float(v/65535) for v in weight_vals], weight_uids) ):
                return False

        with commune.status(":satellite: Setting weights on [white]{}[/white] ...".format(subtensor.network)):
            try:
                with subtensor.substrate as substrate:
                    call = substrate.compose_call(
                        call_module='SubtensorModule',
                        call_function='set_weights',
                        call_params = {
                            'dests': weight_uids,
                            'weights': weight_vals,
                            'netuid': netuid,
                            'version_key': version_key,
                        }
                    )
                    # Period dictates how long the extrinsic will stay as part of waiting pool
                    extrinsic = substrate.create_signed_extrinsic( call = call, keypair = wallet.hotkey, era={'period':100})
                    response = substrate.submit_extrinsic( extrinsic, wait_for_inclusion = wait_for_inclusion, wait_for_finalization = wait_for_finalization )
                    # We only wait here if we expect finalization.
                    if not wait_for_finalization and not wait_for_inclusion:
                        commune.print(":white_heavy_check_mark: [green]Sent[/green]")
                        return True

                    response.process_events()
                    if response.is_success:
                        commune.print(":white_heavy_check_mark: [green]Finalized[/green]")
                        bittensor.logging.success(  prefix = 'Set weights', sufix = '<green>Finalized: </green>' + str(response.is_success) )
                        return True
                    else:
                        commune.print(":cross_mark: [red]Failed[/red]: error:{}".format(response.error_message))
                        bittensor.logging.warning(  prefix = 'Set weights', sufix = '<red>Failed: </red>' + str(response.error_message) )
                        return False

            except Exception as e:
                commune.print(":cross_mark: [red]Failed[/red]: error:{}".format(e))
                bittensor.logging.warning(  prefix = 'Set weights', sufix = '<red>Failed: </red>' + str(e) )
                return False

        if response.is_success:
            commune.print("Set weights:\n[bold white]  weights: {}\n  uids: {}[/bold white ]".format( [float(v/4294967295) for v in weight_vals], weight_uids ))
            message = '<green>Success: </green>' + f'Set {len(uids)} weights, top 5 weights' + str(list(zip(uids.tolist()[:5], [round (w,4) for w in weights.tolist()[:5]] )))
            logger.debug('Set weights:'.ljust(20) +  message)
            return True
        
        return False

    @classmethod
    def name2subnet(cls, name:str) -> int:
        name2subnet = {
            'commune': 0,
            'text': 1,
            # 'image': 2,
            # 'audio': 3,
            # 'image2text': 3,
            # 'text2image': 4,
            # 'speech2text': 5,
            # 'text2speech': 6,
            # 'video': 7,
            # 'video2text': 7,
            # 'text2video': 8,
            # 'video2image': 9,
        }
        subnet = name2subnet.get(name, None)
        
        assert subnet != None, f'Invalid name: {name}, your name must be one of {name2subnet.keys()}'
        
        return subnet
    ######################
    #### Registration ####
    ######################

    def resolve_key(self, key: 'commune.Key') -> 'commune.Key':
        if key == None:
            if not hasattr(self, 'key'):
                self.key = commune.key()
            key = self.key
        
        return key
    
    @classmethod
    def subnets(cls) -> List[int]:
        return self.name2subnet.keys()
    
    
    def resolve_net(self, net: Union[str, int]) -> int:
        if isinstance(net, str):
            net = self.name2subnet(net)
        assert isinstance(net, int), f'Invalid net: {net}, your net must be one of {self.name2subnet.keys()}'
        return net
    
    def register (
        self
        netid :int = 0 ,
        key: 'commune.Key' = None,
        wait_for_inclusion: bool = False,
        wait_for_finalization: bool = True,
        prompt: bool = False,
        max_allowed_attempts: int = 3,
        update_interval: Optional[int] = None,
        log_verbose: bool = False,

    ) -> bool:

        r""" Registers the wallet to chain.
        Args:
            netuid (int):
                The netuid of the subnet to register on.
            wait_for_inclusion (bool):
                If set, waits for the extrinsic to enter a block before returning true, 
                or returns false if the extrinsic fails to enter the block within the timeout.   
            wait_for_finalization (bool):
                If set, waits for the extrinsic to be finalized on the chain before returning true,
                or returns false if the extrinsic fails to be finalized within the timeout.
            prompt (bool):
                If true, the call waits for confirmation from the user before proceeding.
            max_allowed_attempts (int):
                Maximum number of attempts to register the wallet.
            cuda (bool):
                If true, the wallet should be registered using CUDA device(s).
            dev_id (Union[List[int], int]):
                The CUDA device id to use, or a list of device ids.
            TPB (int):
                The number of threads per block (CUDA).
            num_processes (int):
                The number of processes to use to register.
            update_interval (int):
                The number of nonces to solve between updates.
            log_verbose (bool):
                If true, the registration process will log more information.
        Returns:
            success (bool):
                flag is true if extrinsic was finalized or uncluded in the block. 
                If we did not wait for finalization / inclusion, the response is true.
        """
        
        
        key = self.resolve_key(key)
        netuid = self.resolve_net(net)

        
        if not subspace.subnet_exists( netuid ):
            commune.print(":cross_mark: [red]Failed[/red]: error: [bold white]subnet:{}[/bold white] does not exist.".format(netuid))
            return False

        with commune.status(f":satellite: Checking Account on [bold]subnet:{netuid}[/bold]..."):
            neuron = subspace.get_neuron_for_pubkey_and_subnet( key.ss58_address, netuid = netuid )
            if not neuron.is_null:
                commune.print(
                ':white_heavy_check_mark: [green]Already Registered[/green]:\n'\
                'uid: [bold white]{}[/bold white]\n' \
                'netuid: [bold white]{}[/bold white]\n' \
                'hotkey: [bold white]{}[/bold white]\n' \
                'coldkey: [bold white]{}[/bold white]' 
                .format(neuron.uid, neuron.netuid, neuron.hotkey, neuron.coldkey))
                return True


        # Attempt rolling registration.
        attempts = 1
        while True:
            commune.print(":satellite: Registering...({}/{})".format(attempts, max_allowed_attempts))

            # pow failed
            # might be registered already on this subnet
            if (self.is_key_registered(key=key, , netuid = netuid, subspace = subspace, )):
                commune.print(f":white_heavy_check_mark: [green]Already registered on netuid:{netuid}[/green]")
                return True

                with subspace.substrate as substrate:
                    # create extrinsic call
                    call = substrate.compose_call( 
                        call_module='SubspaceModule',  
                        call_function='register', 
                        call_params={ 
                            'netuid': netuid,
                        } 
                    )
                    extrinsic = substrate.create_signed_extrinsic( call = call, keypair = key  )
                    response = substrate.submit_extrinsic( extrinsic, wait_for_inclusion=wait_for_inclusion, wait_for_finalization=wait_for_finalization )
                    
                    # We only wait here if we expect finalization.
                    if not wait_for_finalization and not wait_for_inclusion:
                        commune.print(":white_heavy_check_mark: [green]Sent[/green]")
                        return True
                    
                    # process if registration successful, try again if pow is still valid
                    response.process_events()
                    if not response.is_success:
                        if 'key is already registered' in response.error_message:
                            # Error meant that the key is already registered.
                            commune.print(f":white_heavy_check_mark: [green]Already Registered on [bold]subnet:{netuid}[/bold][/green]")
                            return True

                        commune.print(":cross_mark: [red]Failed[/red]: error:{}".format(response.error_message))
                        time.sleep(0.5)
                    
                    # Successful registration, final check for neuron and pubkey
                    else:
                        commune.print(":satellite: Checking Balance...")
                        is_registered = self.is_key_registered( key=key, subspace = subspace, netuid = netuid )
                        if is_registered:
                            commune.print(":white_heavy_check_mark: [green]Registered[/green]")
                            return True
                        else:
                            # neuron not found, try again
                            commune.print(":cross_mark: [red]Unknown error. Neuron not found.[/red]")
                            continue
            
                    
            if attempts < max_allowed_attempts:
                #Failed registration, retry pow
                attempts += 1
                commune.print( ":satellite: Failed registration, retrying pow ...({}/{})".format(attempts, max_allowed_attempts))
            else:
                # Failed to register after max attempts.
                commune.print( "[red]No more attempts.[/red]" )
                return False 

    ##################
    #### Transfer ####
    ##################
    def transfer(
        self,
        dest: str, 
        amount: Union[Balance, float], 
        wait_for_inclusion: bool = True,
        wait_for_finalization: bool = False,
        prompt: bool = False,
        key: 'commune.Key' =  None,
    ) -> bool:


        # Validate destination address.
        if not is_valid_address_or_public_key( dest ):
            commune.print(":cross_mark: [red]Invalid destination address[/red]:[bold white]\n  {}[/bold white]".format(dest))
            return False

        if isinstance( dest, bytes):
            # Convert bytes to hex string.
            dest = "0x" + dest.hex()


        # Convert to bittensor.Balance
        if not isinstance(amount, Balance ):
            transfer_balance = Balance.from_tao( amount )
        else:
            transfer_balance = amount

        # Check balance.
        with commune.status(":satellite: Checking Balance..."):
            account_balance = subspace.get_balance( key.ss58_address )
            # check existential deposit.
            existential_deposit = subspace.get_existential_deposit()

        with commune.status(":satellite: Transferring..."):
            with subspace.substrate as substrate:
                call = substrate.compose_call(
                    call_module='Balances',
                    call_function='transfer',
                    call_params={
                        'dest': dest, 
                        'value': transfer_balance.rao
                    }
                )

                try:
                    payment_info = substrate.get_payment_info( call = call, keypair = key )
                except Exception as e:
                    commune.print(":cross_mark: [red]Failed to get payment info[/red]:[bold white]\n  {}[/bold white]".format(e))
                    payment_info = {
                        'partialFee': 2e7, # assume  0.02 Tao 
                    }

                fee = bittensor.Balance.from_rao( payment_info['partialFee'] )
        
        if not keep_alive:
            # Check if the transfer should keep_alive the account
            existential_deposit = Balance(0)

        # Check if we have enough balance.
        if account_balance < (transfer_balance + fee + existential_deposit):
            commune.print(":cross_mark: [red]Not enough balance[/red]:[bold white]\n  balance: {}\n  amount: {}\n  for fee: {}[/bold white]".format( account_balance, transfer_balance, fee ))
            return False

        # Ask before moving on.
        if prompt:
            if not Confirm.ask("Do you want to transfer:[bold white]\n  amount: {}\n  from: {}:{}\n  to: {}\n  for fee: {}[/bold white]".format( transfer_balance, wallet.name, key.ss58_address, dest, fee )):
                return False

        with commune.status(":satellite: Transferring..."):
            with subspace.substrate as substrate:
                call = substrate.compose_call(
                    call_module='Balances',
                    call_function='transfer',
                    call_params={
                        'dest': dest, 
                        'value': transfer_balance.rao
                    }
                )

                extrinsic = substrate.create_signed_extrinsic( call = call, keypair = key )
                response = substrate.submit_extrinsic( extrinsic, wait_for_inclusion = wait_for_inclusion, wait_for_finalization = wait_for_finalization )
                # We only wait here if we expect finalization.
                if not wait_for_finalization and not wait_for_inclusion:
                    commune.print(":white_heavy_check_mark: [green]Sent[/green]")
                    return True

                # Otherwise continue with finalization.
                response.process_events()
                if response.is_success:
                    commune.print(":white_heavy_check_mark: [green]Finalized[/green]")
                    block_hash = response.block_hash
                    commune.print("[green]Block Hash: {}[/green]".format( block_hash ))
                else:
                    commune.print(":cross_mark: [red]Failed[/red]: error:{}".format(response.error_message))

        if response.is_success:
            with .status(":satellite: Checking Balance..."):
                new_balance = subspace.get_balance( key.ss58_address )
                commune.print("Balance:\n  [blue]{}[/blue] :arrow_right: [green]{}[/green]".format(account_balance, new_balance))
                return True
        
        return False

    def get_existential_deposit(
        self,
        block: Optional[int] = None,
    ) -> Optional[Balance]:
        """ Returns the existential deposit for the chain. """
        result = self.query_constant(
            module_name='Balances',
            constant_name='ExistentialDeposit',
            block = block,
        )
        
        if result is None:
            return None
        
        return Balance.from_rao(result.value)

    #################
    #### Serving ####
    #################
    def serve (
        self,
        ip: str, 
        port: int, 
        netuid: int = 0,
        key: 'commune.Key' =  None,
        wait_for_inclusion: bool = False,
        wait_for_finalization = True,
        prompt: bool = False,
    ) -> bool:
        r""" Subscribes an bittensor endpoint to the substensor chain.
        Args:
            wallet (bittensor.wallet):
                bittensor wallet object.
            ip (str):
                endpoint host port i.e. 192.122.31.4
            port (int):
                endpoint port number i.e. 9221
            protocol (int):
                int representation of the protocol 
            netuid (int):
                network uid to serve on.
            placeholder1 (int):
                placeholder for future use.
            placeholder2 (int):
                placeholder for future use.
            wait_for_inclusion (bool):
                if set, waits for the extrinsic to enter a block before returning true, 
                or returns false if the extrinsic fails to enter the block within the timeout.   
            wait_for_finalization (bool):
                if set, waits for the extrinsic to be finalized on the chain before returning true,
                or returns false if the extrinsic fails to be finalized within the timeout.
            prompt (bool):
                If true, the call waits for confirmation from the user before proceeding.
        Returns:
            success (bool):
                flag is true if extrinsic was finalized or uncluded in the block. 
                If we did not wait for finalization / inclusion, the response is true.
        """
        params = {
            'ip': net.ip_to_int(ip),
            'port': port,
            'netuid': netuid,
            'key': wallet.coldkeypub.ss58_address,
        }

        with commune.status(":satellite: Checking Axon..."):
            neuron = subspace.get_neuron_for_pubkey_and_subnet( wallet.hotkey.ss58_address, netuid = netuid )
            neuron_up_to_date = not neuron.is_null and params == {
                'ip': net.ip_to_int(neuron.axon_info.ip),
                'port': neuron.axon_info.port,
                'netuid': neuron.netuid,
                'key': neuron.coldkey,
            }

        output = params.copy()
        output['key'] = key.ss58_address

        if neuron_up_to_date:
            commune.print(f":white_heavy_check_mark: [green]Axon already Served[/green]\n"
                                        f"[green not bold]- coldkey: [/green not bold][white not bold]{output['key']}[/white not bold] \n"
                                        f"[green not bold]- Status: [/green not bold] |"
                                        f"[green not bold] ip: [/green not bold][white not bold]{net.int_to_ip(output['ip'])}[/white not bold] |"
                                        f"[green not bold] port: [/green not bold][white not bold]{output['port']}[/white not bold] | "
                                        f"[green not bold] netuid: [/green not bold][white not bold]{output['netuid']}[/white not bold] |"
            )


            return True

        if prompt:
            output = params.copy()
            output['key'] = key.ss58_address
            if not Confirm.ask("Do you want to serve axon:\n  [bold white]{}[/bold white]".format(
                json.dumps(output, indent=4, sort_keys=True)
            )):
                return False

        with commune.status(":satellite: Serving axon on: [white]{}:{}[/white] ...".format(subspace.network, netuid)):
            with subspace.substrate as substrate:
                call = substrate.compose_call(
                    call_module='SubspaceModule',
                    call_function='serve_axon',
                    call_params=params
                )
                extrinsic = substrate.create_signed_extrinsic( call = call, keypair = key)
                response = substrate.submit_extrinsic( extrinsic, wait_for_inclusion = wait_for_inclusion, wait_for_finalization = wait_for_finalization )
                if wait_for_inclusion or wait_for_finalization:
                    response.process_events()
                    if response.is_success:
                        commune.print(':white_heavy_check_mark: [green]Served[/green]\n  [bold white]{}[/bold white]'.format(
                            json.dumps(params, indent=4, sort_keys=True)
                        ))
                        return True
                    else:
                        commune.print(':cross_mark: [green]Failed to Serve axon[/green] error: {}'.format(response.error_message))
                        return False
                else:
                    return True


    def add_stake(
            key_ss58: Optional[str] = None,
            amount: Union[Balance, float] = None, 
            subspace: 'bittensor.Subspace' = None, 
            key: 'commune.Key' = None,
            wait_for_inclusion: bool = True,
            wait_for_finalization: bool = False,
            prompt: bool = False,
        ) -> bool:
        r""" Adds the specified amount of stake to passed hotkey uid.
        Args:
            wallet (bittensor.wallet):
                Bittensor wallet object.
            hotkey_ss58 (Optional[str]):
                ss58 address of the hotkey account to stake to
                defaults to the wallet's hotkey.
            amount (Union[Balance, float]):
                Amount to stake as bittensor balance, or float interpreted as Tao.
            wait_for_inclusion (bool):
                If set, waits for the extrinsic to enter a block before returning true, 
                or returns false if the extrinsic fails to enter the block within the timeout.   
            wait_for_finalization (bool):
                If set, waits for the extrinsic to be finalized on the chain before returning true,
                or returns false if the extrinsic fails to be finalized within the timeout.
            prompt (bool):
                If true, the call waits for confirmation from the user before proceeding.
        Returns:
            success (bool):
                flag is true if extrinsic was finalized or uncluded in the block. 
                If we did not wait for finalization / inclusion, the response is true.

        Raises:
            NotRegisteredError:
                If the wallet is not registered on the chain.
            NotDelegateError:
                If the hotkey is not a delegate on the chain.
        """


        # Flag to indicate if we are using the wallet's own hotkey.
        old_balance = subspace.get_balance( key.ss58_address )
        # Get current stake
        old_stake = subspace.get_stake_for_key( key_ss58=key.ss58_address )

        # Convert to bittensor.Balance
        if amount == None:
            # Stake it all.
            staking_balance = Balance.from_tao( old_balance.tao )
        elif not isinstance(amount, bittensor.Balance ):
            staking_balance = Balance.from_tao( amount )
        else:
            staking_balance = amount

        # Remove existential balance to keep key alive.
        if staking_balance > Balance.from_rao( 1000 ):
            staking_balance = staking_balance - Balance.from_rao( 1000 )
        else:
            staking_balance = staking_balance

        # Check enough to stake.
        if staking_balance > old_balance:
            commune.print(":cross_mark: [red]Not enough stake[/red]:[bold white]\n  balance:{}\n  amount: {}\n  coldkey: {}[/bold white]".format(old_balance, staking_balance, wallet.name))
            return False
                
        # Ask before moving on.
        if prompt:
            if not Confirm.ask("Do you want to stake:[bold white]\n  amount: {}\n  to: {}[/bold white]".format( staking_balance, key.ss58_address) ):
                return False

        try:
            with commune.status(":satellite: Staking to: [bold white]{}[/bold white] ...".format(subspace.network)):

                with subspace.substrate as substrate:
                    call = substrate.compose_call(
                    call_module='SubspaceModule', 
                    call_function='add_stake',
                    call_params={
                        'key': key.ss58_address,
                        'amount_staked': amount.rao
                        }
                    )
                    extrinsic = substrate.create_signed_extrinsic( call = call, keypair = key )
                    response = substrate.submit_extrinsic( extrinsic, wait_for_inclusion = wait_for_inclusion, wait_for_finalization = wait_for_finalization )


            if response: # If we successfully staked.
                # We only wait here if we expect finalization.
                if not wait_for_finalization and not wait_for_inclusion:
                    commune.print(":white_heavy_check_mark: [green]Sent[/green]")
                    return True

                commune.print(":white_heavy_check_mark: [green]Finalized[/green]")
                with commune.status(":satellite: Checking Balance on: [white]{}[/white] ...".format(subspace.network)):
                    new_balance = subspace.get_balance( address = key.ss58_address )
                    block = subspace.get_current_block()
                    new_stake = subspace.get_stake_for_key(key_ss58=key.ss58_address,block=block) # Get current stake

                    commune.print("Balance:\n  [blue]{}[/blue] :arrow_right: [green]{}[/green]".format( old_balance, new_balance ))
                    commune.print("Stake:\n  [blue]{}[/blue] :arrow_right: [green]{}[/green]".format( old_stake, new_stake ))
                    return True
            else:
                commune.print(":cross_mark: [red]Failed[/red]: Error unknown.")
                return False

        except NotRegisteredError as e:
            commune.print(":cross_mark: [red]Hotkey: {} is not registered.[/red]".format(key.ss58_address))
            return False
        except StakeError as e:
            commune.print(":cross_mark: [red]Stake Error: {}[/red]".format(e))
            return False





    def unstake (
            self,
            amount: Union[Balance, float] = None, 
            key: 'commune.Key' = None,
            subspace: 'commune.Subspace' = None,
            wait_for_inclusion:bool = True, 
            wait_for_finalization:bool = False,
            prompt: bool = False,
        ) -> bool:
        r""" Removes stake into the wallet coldkey from the specified hotkey uid.
        Args:
            wallet (bittensor.wallet):
                bittensor wallet object.
            key_ss58 (Optional[str]):
                ss58 address of the hotkey to unstake from.
                by default, the wallet hotkey is used.
            amount (Union[Balance, float]):
                Amount to stake as bittensor balance, or float interpreted as tao.
            wait_for_inclusion (bool):
                if set, waits for the extrinsic to enter a block before returning true, 
                or returns false if the extrinsic fails to enter the block within the timeout.   
            wait_for_finalization (bool):
                if set, waits for the extrinsic to be finalized on the chain before returning true,
                or returns false if the extrinsic fails to be finalized within the timeout.
            prompt (bool):
                If true, the call waits for confirmation from the user before proceeding.
        Returns:
            success (bool):
                flag is true if extrinsic was finalized or uncluded in the block. 
                If we did not wait for finalization / inclusion, the response is true.
        """
        with commune.status(":satellite: Syncing with chain: [white]{}[/white] ...".format(subspace.network)):
            old_balance = subspace.get_balance( key.ss58_address )        
            old_stake = subspace.get_stake_for_key( key_ss58 = key.ss58_address)

        # Convert to bittensor.Balance
        if amount == None:
            # Unstake it all.
            unstaking_balance = old_stake
        elif not isinstance(amount, Balance ):
            unstaking_balance = Balance.from_tao( amount )
        else:
            unstaking_balance = amount

        # Check enough to unstake.
        stake_on_uid = old_stake
        if unstaking_balance > stake_on_uid:
            commune.print(":cross_mark: [red]Not enough stake[/red]: [green]{}[/green] to unstake: [blue]{}[/blue] from key: [white]{}[/white]".format(stake_on_uid, unstaking_balance, key.ss58_address))
            return False
        
        # Ask before moving on.
        if prompt:
            if not Confirm.ask("Do you want to unstake:\n[bold white]  amount: {} key: [white]{}[/bold white ]\n?".format( unstaking_balance, key.ss58_address) ):
                return False

        
        try:
            with commune.status(":satellite: Unstaking from chain: [white]{}[/white] ...".format(subspace.network)):


                with subspace.substrate as substrate:
                    call = substrate.compose_call(
                    call_module='SubspaceModule', 
                    call_function='remove_stake',
                    call_params={
                        'hotkey': key.ss58_address,
                        'amount_unstaked': amount.rao
                        }
                    )
                    extrinsic = substrate.create_signed_extrinsic( call = call, keypair = key )
                    response = substrate.submit_extrinsic( extrinsic, wait_for_inclusion = wait_for_inclusion, wait_for_finalization = wait_for_finalization )
                    # We only wait here if we expect finalization.
                    if not wait_for_finalization and not wait_for_inclusion:
                        return True

                    response.process_events()


            if response: # If we successfully unstaked.
                # We only wait here if we expect finalization.
                if not wait_for_finalization and not wait_for_inclusion:
                    commune.print(":white_heavy_check_mark: [green]Sent[/green]")
                    return True

                commune.print(":white_heavy_check_mark: [green]Finalized[/green]")
                with commune.status(":satellite: Checking Balance on: [white]{}[/white] ...".format(subspace.network)):
                    new_balance = subspace.get_balance( address = key.ss58_address )
                    new_stake = subspace.get_stake_for_key( key_ss58 = key.ss58_address ) # Get stake on hotkey.
                    commune.print("Balance:\n  [blue]{}[/blue] :arrow_right: [green]{}[/green]".format( old_balance, new_balance ))
                    commune.print("Stake:\n  [blue]{}[/blue] :arrow_right: [green]{}[/green]".format( old_stake, new_stake ))
                    return True
            else:
                commune.print(":cross_mark: [red]Failed[/red]: Error unknown.")
                return False

        except NotRegisteredError as e:
            commune.print(":cross_mark: [red]Hotkey: {} is not registered.[/red]".format(key.ss58_address))
            return False
        except StakeError as e:
            commune.print(":cross_mark: [red]Stake Error: {}[/red]".format(e))
            return False

    ########################
    #### Standard Calls ####
    ########################

    """ Queries subspace named storage with params and block. """
    def query_subspace( self, name: str, block: Optional[int] = None, params: Optional[List[object]] = [] ) -> Optional[object]:
        @retry(delay=2, tries=3, backoff=2, max_delay=4)
        def make_substrate_call_with_retry():
            with self.substrate as substrate:
                return substrate.query(
                    module='SubspaceModule',
                    storage_function = name,
                    params = params,
                    block_hash = None if block == None else substrate.get_block_hash(block)
                )
        return make_substrate_call_with_retry()

    """ Queries subspace map storage with params and block. """
    def query_map_subspace( self, name: str, block: Optional[int] = None, params: Optional[List[object]] = [] ) -> Optional[object]:
        @retry(delay=2, tries=3, backoff=2, max_delay=4)
        def make_substrate_call_with_retry():
            with self.substrate as substrate:
                return substrate.query_map(
                    module='SubspaceModule',
                    storage_function = name,
                    params = params,
                    block_hash = None if block == None else substrate.get_block_hash(block)
                )
        return make_substrate_call_with_retry()
    
    """ Gets a constant from subspace with module_name, constant_name, and block. """
    def query_constant( self, module_name: str, constant_name: str, block: Optional[int] = None ) -> Optional[object]:
        @retry(delay=2, tries=3, backoff=2, max_delay=4)
        def make_substrate_call_with_retry():
            with self.substrate as substrate:
                return substrate.get_constant(
                    module_name=module_name,
                    constant_name=constant_name,
                    block_hash = None if block == None else substrate.get_block_hash(block)
                )
        return make_substrate_call_with_retry()
      
    #####################################
    #### Hyper parameter calls. ####
    #####################################

    """ Returns network Rho hyper parameter """
    def rho (self, netuid: int, block: Optional[int] = None ) -> Optional[int]:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace( "Rho", block, [netuid] ).value

    """ Returns network Kappa hyper parameter """
    def kappa (self, netuid: int, block: Optional[int] = None ) -> Optional[float]:
        if not self.subnet_exists( netuid ): return None
        return U16_NORMALIZED_FLOAT( self.query_subspace( "Kappa", block, [netuid] ).value )

    """ Returns network Difficulty hyper parameter """
    def difficulty (self, netuid: int, block: Optional[int] = None ) -> Optional[int]:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace( "Difficulty", block, [netuid] ).value
    
    """ Returns network Burn hyper parameter """
    def burn (self, netuid: int, block: Optional[int] = None ) -> Optional[bittensor.Balance]:
        if not self.subnet_exists( netuid ): return None
        return bittensor.Balance.from_rao( self.query_subspace( "Burn", block, [netuid] ).value )

    """ Returns network ImmunityPeriod hyper parameter """
    def immunity_period (self, netuid: int, block: Optional[int] = None ) -> Optional[int]:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace("ImmunityPeriod", block, [netuid] ).value

    """ Returns network ValidatorBatchSize hyper parameter """
    def validator_batch_size (self, netuid: int, block: Optional[int] = None ) -> Optional[int]:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace("ValidatorBatchSize", block, [netuid] ).value

    """ Returns network ValidatorPruneLen hyper parameter """
    def validator_prune_len (self, netuid: int, block: Optional[int] = None ) -> int:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace("ValidatorPruneLen", block, [netuid] ).value

    """ Returns network ValidatorLogitsDivergence hyper parameter """
    def validator_logits_divergence (self, netuid: int, block: Optional[int] = None ) -> Optional[float]:
        if not self.subnet_exists( netuid ): return None
        return U16_NORMALIZED_FLOAT(self.query_subspace("ValidatorLogitsDivergence", block, [netuid]).value)

    """ Returns network ValidatorSequenceLength hyper parameter """
    def validator_sequence_length (self, netuid: int, block: Optional[int] = None ) -> Optional[int]:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace("ValidatorSequenceLength", block, [netuid] ).value

    """ Returns network ValidatorEpochsPerReset hyper parameter """
    def validator_epochs_per_reset (self, netuid: int, block: Optional[int] = None ) -> Optional[int]:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace("ValidatorEpochsPerReset", block, [netuid] ).value

    """ Returns network ValidatorEpochLen hyper parameter """
    def validator_epoch_length (self, netuid: int, block: Optional[int] = None ) -> Optional[int]:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace("ValidatorEpochLen", block, [netuid] ).value

    """ Returns network ValidatorEpochLen hyper parameter """
    def validator_exclude_quantile (self, netuid: int, block: Optional[int] = None ) -> Optional[float]:
        if not self.subnet_exists( netuid ): return None
        return U16_NORMALIZED_FLOAT( self.query_subspace("ValidatorExcludeQuantile", block, [netuid] ).value )

    """ Returns network MaxAllowedValidators hyper parameter """
    def max_allowed_validators(self, netuid: int, block: Optional[int] = None) -> Optional[int]:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace( 'MaxAllowedValidators', block, [netuid] ).value
        
    """ Returns network MinAllowedWeights hyper parameter """
    def min_allowed_weights (self, netuid: int, block: Optional[int] = None ) -> Optional[int]:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace("MinAllowedWeights", block, [netuid] ).value

    """ Returns network MaxWeightsLimit hyper parameter """
    def max_weight_limit (self, netuid: int, block: Optional[int] = None ) -> Optional[float]:
        if not self.subnet_exists( netuid ): return None
        return U16_NORMALIZED_FLOAT( self.query_subspace('MaxWeightsLimit', block, [netuid] ).value )

    """ Returns network ScalingLawPower hyper parameter """
    def scaling_law_power (self, netuid: int, block: Optional[int] = None ) -> Optional[float]:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace('ScalingLawPower', block, [netuid] ).value / 100.

    """ Returns network SynergyScalingLawPower hyper parameter """
    def synergy_scaling_law_power (self, netuid: int, block: Optional[int] = None ) -> Optional[float]:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace('SynergyScalingLawPower', block, [netuid] ).value / 100.

    """ Returns network SubnetworkN hyper parameter """
    def subnetwork_n (self, netuid: int, block: Optional[int] = None ) -> int:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace('SubnetworkN', block, [netuid] ).value

    """ Returns network MaxAllowedUids hyper parameter """
    def max_n (self, netuid: int, block: Optional[int] = None ) -> Optional[int]:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace('MaxAllowedUids', block, [netuid] ).value

    """ Returns network BlocksSinceLastStep hyper parameter """
    def blocks_since_epoch (self, netuid: int, block: Optional[int] = None) -> int:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace('BlocksSinceLastStep', block, [netuid] ).value

    """ Returns network Tempo hyper parameter """
    def tempo (self, netuid: int, block: Optional[int] = None) -> int:
        if not self.subnet_exists( netuid ): return None
        return self.query_subspace('Tempo', block, [netuid] ).value

    ##########################
    #### Account functions ###
    ##########################

    """ Returns the total stake held on a coldkey across all hotkeys including delegates"""
    def get_total_stake_for_key( self, ss58_address: str, block: Optional[int] = None ) -> Optional['bittensor.Balance']:
        return bittensor.Balance.from_rao( self.query_subspace( 'TotalKeyStake', block, [ss58_address] ).value )

    """ Returns the stake under a coldkey - hotkey pairing """
    def get_stake_for_key( self, key_ss58: str, block: Optional[int] = None ) -> Optional['bittensor.Balance']:
        return bittensor.Balance.from_rao( self.query_subspace( 'Stake', block, [key_ss58] ).value )

    """ Returns a list of stake tuples (coldkey, balance) for each delegating coldkey including the owner"""
    def get_stake( self,  key_ss58: str, block: Optional[int] = None ) -> List[Tuple[str,'bittensor.Balance']]:
        return [ (r[0].value, bittensor.Balance.from_rao( r[1].value ))  for r in self.query_map_subspace( 'Stake', block, [key_ss58] ) ]

    """ Returns the axon information for this key account """
    def get_axon_info( self, key_ss58: str, block: Optional[int] = None ) -> Optional[AxonInfo]:
        result = self.query_subspace( 'Axons', block, [key_ss58 ] )        
        if result != None:
            return AxonInfo(
                ip = commune.utils.networking.ip_from_int( result.value.ip ),
                port = result.value.port,
            )
        else:
            return None


    ###########################
    #### Global Parameters ####
    ###########################

    @property
    def block (self) -> int:
        r""" Returns current chain block.
        Returns:
            block (int):
                Current chain block.
        """
        return self.get_current_block()

    def total_issuance (self, block: Optional[int] = None ) -> 'bittensor.Balance':
        return bittensor.Balance.from_rao( self.query_subspace( 'TotalIssuance', block ).value )

    def total_stake (self,block: Optional[int] = None ) -> 'bittensor.Balance':
        return bittensor.Balance.from_rao( self.query_subspace( "TotalStake", block ).value )

    def serving_rate_limit (self, block: Optional[int] = None ) -> Optional[int]:
        return self.query_subspace( "ServingRateLimit", block ).value

    #####################################
    #### Network Parameters ####
    #####################################

    def subnet_exists( self, netuid: int, block: Optional[int] = None ) -> bool:
        return self.query_subspace( 'NetworksAdded', block, [netuid] ).value  

    def get_all_subnet_netuids( self, block: Optional[int] = None ) -> List[int]:
        subnet_netuids = []
        result = self.query_map_subspace( 'NetworksAdded', block )
        if result.records:
            for netuid, exists in result:  
                if exists:
                    subnet_netuids.append( netuid.value )
            
        return subnet_netuids

    def get_total_subnets( self, block: Optional[int] = None ) -> int:
        return self.query_subspace( 'TotalNetworks', block ).value      

    def get_subnet_modality( self, netuid: int, block: Optional[int] = None ) -> Optional[int]:
        return self.query_subspace( 'NetworkModality', block, [netuid] ).value   

    def get_subnet_connection_requirement( self, netuid_0: int, netuid_1: int, block: Optional[int] = None) -> Optional[int]:
        return self.query_subspace( 'NetworkConnect', block, [netuid_0, netuid_1] ).value

    def get_emission_value_by_subnet( self, netuid: int, block: Optional[int] = None ) -> Optional[float]:
        return bittensor.Balance.from_rao( self.query_subspace( 'EmissionValues', block, [ netuid ] ).value )

    def get_subnet_connection_requirements( self, netuid: int, block: Optional[int] = None) -> Dict[str, int]:
        result = self.query_map_subspace( 'NetworkConnect', block, [netuid] )
        if result.records:
            requirements = {}
            for tuple in result.records:
                requirements[str(tuple[0].value)] = tuple[1].value
        else:
            return {}

    def get_subnets( self, block: Optional[int] = None ) -> List[int]:
        subnets = []
        result = self.query_map_subspace( 'NetworksAdded', block )
        if result.records:
            for network in result.records:
                subnets.append( network[0].value )
            return subnets
        else:
            return []

    def get_all_subnets_info( self, block: Optional[int] = None ) -> List[SubnetInfo]:
        @retry(delay=2, tries=3, backoff=2, max_delay=4)
        def make_substrate_call_with_retry():
            with self.substrate as substrate:
                block_hash = None if block == None else substrate.get_block_hash( block )
                params = []
                if block_hash:
                    params = params + [block_hash]
                return substrate.rpc_request(
                    method="subnetInfo_getSubnetsInfo", # custom rpc method
                    params=params
                )
        
        json_body = make_substrate_call_with_retry()
        result = json_body['result']

        if result in (None, []):
            return []
        
        return SubnetInfo.list_from_vec_u8( result )

    def get_subnet_info( self, netuid: int, block: Optional[int] = None ) -> Optional[SubnetInfo]:
        @retry(delay=2, tries=3, backoff=2, max_delay=4)
        def make_substrate_call_with_retry():
            with self.substrate as substrate:
                block_hash = None if block == None else substrate.get_block_hash( block )
                params = [netuid]
                if block_hash:
                    params = params + [block_hash]
                return substrate.rpc_request(
                    method="subnetInfo_getSubnetInfo", # custom rpc method
                    params=params
                )
        
        json_body = make_substrate_call_with_retry()
        result = json_body['result']

        if result in (None, []):
            return None
        
        return SubnetInfo.from_vec_u8( result )


    ########################################
    #### Neuron information per subnet ####
    ########################################

    def is_key_registered_any( self, key: str = None, block: Optional[int] = None) -> bool:
        key = self.resolve_key( key )
        return len( self.get_netuids_for_key( key.ss58_address, block) ) > 0
    
    def is_key_registered_on_subnet( self, key_ss58: str, netuid: int, block: Optional[int] = None) -> bool:
        return self.get_uid_for_key_on_subnet( key_ss58, netuid, block ) != None

    def is_key_registered( self, key_ss58: str, netuid: int, block: Optional[int] = None) -> bool:
        return self.get_uid_for_key_on_subnet( key_ss58, netuid, block ) != None

    def get_uid_for_key_on_subnet( self, key_ss58: str, netuid: int, block: Optional[int] = None) -> int:
        return self.query_subspace( 'Uids', block, [ netuid, key_ss58 ] ).value  

    def get_all_uids_for_key( self, key_ss58: str, block: Optional[int] = None) -> List[int]:
        return [ self.get_uid_for_key_on_subnet( key_ss58, netuid, block) for netuid in self.get_netuids_for_key( key_ss58, block)]

    def get_netuids_for_key( self, key_ss58: str, block: Optional[int] = None) -> List[int]:
        result = self.query_map_subspace( 'IsNetworkMember', block, [ key_ss58 ] )   
        netuids = []
        for netuid, is_member in result.records:
            if is_member:
                netuids.append( netuid.value )
        return netuids

    def get_neuron_for_pubkey_and_subnet( self, key_ss58: str, netuid: int, block: Optional[int] = None ) -> Optional[NeuronInfo]:
        return self.neuron_for_uid( self.get_uid_for_key_on_subnet(key_ss58, netuid, block=block), netuid, block = block)

    def get_all_neurons_for_key( self, key_ss58: str, block: Optional[int] = None ) -> List[NeuronInfo]:
        netuids = self.get_netuids_for_key( key_ss58, block) 
        uids = [self.get_uid_for_key_on_subnet(key_ss58, net) for net in netuids] 
        return [self.neuron_for_uid( uid, net ) for uid, net in list(zip(uids, netuids))]

    def neuron_has_validator_permit( self, uid: int, netuid: int, block: Optional[int] = None ) -> Optional[bool]:
        return self.query_subspace( 'ValidatorPermit', block, [ netuid, uid ] ).value

    def neuron_for_wallet( self, key: 'commune.Key', netuid = int, block: Optional[int] = None ) -> Optional[NeuronInfo]: 
        return self.get_neuron_for_pubkey_and_subnet ( key.ss58_address, netuid = netuid, block = block )

    def neuron_for_uid( self, uid: int, netuid: int, block: Optional[int] = None ) -> Optional[NeuronInfo]: 
        r""" Returns a list of neuron from the chain. 
        Args:
            uid ( int ):
                The uid of the neuron to query for.
            netuid ( int ):
                The uid of the network to query for.
            block ( int ):
                The neuron at a particular block
        Returns:
            neuron (Optional[NeuronInfo]):
                neuron metadata associated with uid or None if it does not exist.
        """
        if uid == None: return NeuronInfo._null_neuron()
        @retry(delay=2, tries=3, backoff=2, max_delay=4)
        def make_substrate_call_with_retry():
            with self.substrate as substrate:
                block_hash = None if block == None else substrate.get_block_hash( block )
                params = [netuid, uid]
                if block_hash:
                    params = params + [block_hash]
                return substrate.rpc_request(
                    method="neuronInfo_getNeuron", # custom rpc method
                    params=params
                )
        json_body = make_substrate_call_with_retry()
        result = json_body['result']

        if result in (None, []):
            return NeuronInfo._null_neuron()
        
        return NeuronInfo.from_vec_u8( result ) 

    def neurons(self, netuid: int, block: Optional[int] = None ) -> List[NeuronInfo]: 
        r""" Returns a list of neuron from the chain. 
        Args:
            netuid ( int ):
                The netuid of the subnet to pull neurons from.
            block ( Optional[int] ):
                block to sync from.
        Returns:
            neuron (List[NeuronInfo]):
                List of neuron metadata objects.
        """
        @retry(delay=2, tries=3, backoff=2, max_delay=4)
        def make_substrate_call_with_retry():
            with self.substrate as substrate:
                block_hash = None if block == None else substrate.get_block_hash( block )
                params = [netuid]
                if block_hash:
                    params = params + [block_hash]
                return substrate.rpc_request(
                    method="neuronInfo_getNeurons", # custom rpc method
                    params=params
                )
        
        json_body = make_substrate_call_with_retry()
        result = json_body['result']

        if result in (None, []):
            return []
        
        return NeuronInfo.list_from_vec_u8( result )

    def metagraph( self, netuid: int, block: Optional[int] = None ) -> 'bittensor.Metagraph':
        r""" Returns the metagraph for the subnet.
        Args:
            netuid ( int ):
                The network uid of the subnet to query.
            block (Optional[int]):
                The block to create the metagraph for.
                Defaults to latest.
        Returns:
            metagraph ( `bittensor.Metagraph` ):
                The metagraph for the subnet at the block.
        """
        status: Optional['rich.console.Status'] = None
        if bittensor.__use_console__:
            status = commune.status("Synchronizing Metagraph...", spinner="earth")
            status.start()
        

        neurons = self.neurons( netuid = netuid, block = block )
        
        # Get subnet info.
        subnet_info: Optional[bittensor.SubnetInfo] = self.get_subnet_info( netuid = netuid, block = block )
        if subnet_info == None:
            status.stop() if status else ...
            raise ValueError('Could not find subnet info for netuid: {}'.format(netuid))

        status.stop() if status else ...

        # Create metagraph.
        block_number = self.block
        
        metagraph = bittensor.metagraph.from_neurons( network = self.network, netuid = netuid, info = subnet_info, neurons = neurons, block = block_number )
        print("Metagraph subspace: ", self.network)
        return metagraph

    ################
    #### Transfer ##
    ################


    

    ################
    #### Legacy ####
    ################

    def get_balance(self, address: str, block: int = None) -> Balance:
        r""" Returns the token balance for the passed ss58_address address
        Args:
            address (Substrate address format, default = 42):
                ss58 chain address.
        Return:
            balance (bittensor.utils.balance.Balance):
                account balance
        """
        try:
            @retry(delay=2, tries=3, backoff=2, max_delay=4)
            def make_substrate_call_with_retry():
                with self.substrate as substrate:
                    return substrate.query(
                        module='System',
                        storage_function='Account',
                        params=[address],
                        block_hash = None if block == None else substrate.get_block_hash( block )
                    )
            result = make_substrate_call_with_retry()
        except scalecodec.exceptions.RemainingScaleBytesNotEmptyException:
            logger.critical("Your wallet it legacy formatted, you need to run btcli stake --ammount 0 to reformat it." )
            return Balance(1000)
        return Balance( result.value['data']['free'] )

    def get_current_block(self) -> int:
        r""" Returns the current block number on the chain.
        Returns:
            block_number (int):
                Current chain blocknumber.
        """        
        @retry(delay=2, tries=3, backoff=2, max_delay=4)
        def make_substrate_call_with_retry():
            with self.substrate as substrate:
                return substrate.get_block_number(None)
        return make_substrate_call_with_retry()

    def get_balances(self, block: int = None) -> Dict[str, Balance]:
        @retry(delay=2, tries=3, backoff=2, max_delay=4)
        def make_substrate_call_with_retry():
            with self.substrate as substrate:
                return substrate.query_map(
                    module='System',
                    storage_function='Account',
                    block_hash = None if block == None else substrate.get_block_hash( block )
                )
        result = make_substrate_call_with_retry()
        return_dict = {}
        for r in result:
            bal = bittensor.Balance( int( r[1]['data']['free'].value ) )
            return_dict[r[0].value] = bal
        return return_dict

    @staticmethod
    def _null_neuron() -> NeuronInfo:
        neuron = NeuronInfo(
            uid = 0,
            netuid = 0,
            active =  0,
            stake = '0',
            rank = 0,
            emission = 0,
            incentive = 0,
            consensus = 0,
            trust = 0,
            dividends = 0,
            last_update = 0,
            weights = [],
            bonds = [],
            is_null = True,
            key = "000000000000000000000000000000000000000000000000",
        )
        return neuron