import http.client
import json
import commune as c




class BitAPAI(c.Module):
    def __init__(self,  config=None,  **kwargs):
        config = self.set_config(config=config, kwargs=kwargs)
        self.conn = http.client.HTTPSConnection(self.config.host)
        self.api_key=config.api_key

    @classmethod
    def set_api_key(cls, api_key:str):
        assert isinstance(api_key, str)
        cls.putc('api_key', api_key)

    def build_payload(self, text: str, history:list):

        return payload
    
    
    def forward( self, 
                text:str ,
                # api default is 20, I would not go less than 10 with current network conditions
                # larger number = higher query spread across top miners but slightly longer query time
                 count:int = 5,
                 # changed to False, I assume you only want a single repsonse so it will return a single random from the pool of valid responses
                 return_all:bool = False,
                 # added exclude_unavailable to ensure no empty responses are returned
                 exclude_unavailable:bool = True,
                 uids = None,
                 api_key:str = None, history:list=None): 
        api_key = api_key if api_key != None else self.api_key
        # build payload


        payload =  {
            'messages': 
                    [
                    {
                        "role": "system",
                        "content": "You are an AI assistant"
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                    ],
            "count": count,
            "return_all": return_all,
            # added return all here
            "exclude_unavailable": exclude_unavailable

        }
        if uids is not None:
            payload['uids'] = uids

        if history is not None:
            assert isinstance(history, list)
            assert len(history) > 0
            assert all([isinstance(i, dict) for i in history])
            payload = payload[:1] +  history + payload[1:]


        payload = json.dumps(payload)
        headers = {
        'Content-Type': 'application/json',
        'X-API-KEY': api_key
        }
        self.conn.request("POST", "/text", payload, headers)
        res = self.conn.getresponse()
        data = res.read().decode("utf-8")
        c.print(data)
        data = json.loads(data)
        if 'assistant' not in data:
            return data
        return data['assistant']
    
    
    talk = generate = forward
    
    def test(self):
        return self.forward("hello")