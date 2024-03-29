from copy import deepcopy
from datetime import datetime
from pytz import timezone

# GERENCIA A POSTAGEM DE VÍDEOS NO TWITTER
class YoutubeToTwitter():
    def __init__(self, mongo_connector, youtube_handler, twitter_connector,
                 twitter_to_telegram):
        self.mongo_conn = mongo_connector.setDatabase().setCollection()
        self.yt_handler = youtube_handler
        self.twitter = twitter_connector
        self.telegram = twitter_to_telegram


    # RETORNA UMA LISTA COM OS ELEMENTOS DA "list1" QUE NÃO EXISTEM NA "list2"
    def filterNotMatches(self, list1, list2):
        return list(set(list1) - set(list2))


    # Dormir com contagem regrassiva
    def sleep(self, time, indent_size=0, include_text=''):
        from time import sleep
        from sys import stdout
        tabs = '\t' * indent_size
        for remaining in range(time, 0, -1):
            stdout.write("\r")
            stdout.write(
                f"{tabs}{include_text} retomará em {remaining} segundos..."
            )
            stdout.flush()
            sleep(1)

        stdout.write(f"\r{tabs}{include_text} Pronto!\n")

    
    # RETORNA UM DICIONÁRIO ONDE AS CHAVES SÃO OS IDs DOS CANAIS
    # E O VALOR É UMA LISTA COM OS IDs DOS VÍDEOS ÚLTIMOS QUE AINDA NÃO FORAM
    # ANALISADOS (QUE ESTÃO ARMAZENADOS DO BANCO DE DADOS)
    # "size_list" DEFINE QUANTOS ELEMENTOS SERÃO PESQUISADOS NA API DO GOOGLES
    # (A API PODE RETORNAR VÍDEOS OS PLAYLISTS, ONDE AS PLAYLISTS SERÃO
    # DESCARTADAS — AFETANDO O TOTAL DE VÍDEOS RETORNADOS)
    def getAllUnsendVideos(self, size_list=5):
        dict_unsend = dict()
        for document in self.mongo_conn.getAllDocuments():
            print(f"{document['name']} ({document['_id']})", end=': ')

            channel_unsend_vids = self.getChannelUnsendVideos(document,
                                                              size_list)
            dict_unsend.update(channel_unsend_vids)
            not_matches_list = channel_unsend_vids[document['_id']]

            print( len(not_matches_list), not_matches_list )

        return dict_unsend


    # RETORNA UM DICIONÁRIO COM O ID DO CANAIS E OS IDs DOS VÍDEOS ÚLTIMOS QUE
    # AINDA NÃO FORAM ANALISADOS.
    # MAIS DETALHES EM "getAllUnsendVideos()"
    def getChannelUnsendVideos(self, document, size_list=5):
        self.yt_handler.loadListVideos(document['_id'], size_list)
        video_id_list = self.yt_handler.getVideoIDList()
        not_matches_list = self.filterNotMatches(
            video_id_list, document['video_ids']
        )

        return {document['_id']: not_matches_list}


    # Atualiza Banco de Dados Mongo com os Canais que estão no TXT
    def updateYoutubeChannelsCollection(
        self, youtube_channel_ids_url=(
            'https://raw.githubusercontent.com/Crissky/game_loot_news_bot/main/'
            'youtube_channel_ids.txt'
        )
    ):
        import requests
        from pytube import YouTube
        response = requests.get(youtube_channel_ids_url)
        youtube_channel_ids = response.text.splitlines()

        # print("youtube_channel_ids:\n", '\n'.join(youtube_channel_ids))

        for channel_id in youtube_channel_ids:
            document = self.mongo_conn.getDocumentByID(channel_id)
            if document:
                print(
                    f'Canal {document["name"]} já existe no banco de dados com '
                    f'o ID: {document["_id"]}.'
                )
                continue

            self.yt_handler.loadListVideos(channel_id, 50)
            video_url = self.yt_handler.getLastVideoURL()
            try:
                youtube = YouTube(video_url)
                channel_name = youtube.author

                yt_channel_model = YoutubeChannelsModel(channel_id,
                                                        channel_name)
                self.mongo_conn.collection.insert_one(yt_channel_model.data)
                print(
                    f'O canal {channel_name}, de id: {channel_id}, foi inserido '
                    f'no banco de dados.'
                    )
            except Exception as e:
                print('O canal de id:', channel_id,
                      'Não pode ser atualizado com a URL:', video_url)
                print('Motivo:', e)


    # Retorna uma lista com os IDs dos canais restritos
    # Canais restritos são aqueles que produzem outros conteúdos
    # além dos trailers de jogos
    # Exemplo: IGN
    def getRestrictedChannelIDs(self):
        self.mongo_conn.setCollection('restrictedChannels')
        document = self.mongo_conn.collection.find_one()
        self.mongo_conn.setCollection()

        channel_ids = document['channels']

        return channel_ids


    # Retorna True caso o canal não esteja na lista de canais restritos
    # ou se ele estiver na lista, mas contém a palavra trailer título do vídeo
    def isRestrictedTrailer(self, channel_id, youtube):
        channel_ids = self.getRestrictedChannelIDs()
        my_bool = True
        if (channel_id in channel_ids):
            title = youtube.title.lower()
            description = youtube.description.lower()
            my_bool = 'trailer' in title\
                    and 'netflix' not in title\
                    and 'netflix' not in description\
                    and 'marvel studios' not in title\
                    and 'marvel studios' not in description\
                    and 'ign daily' not in title\
                    and 'ign daily' not in description\


        return my_bool


    # Envia um Vídeo para o Twitter usando a URL do vídeo no YouTube.
    def sendSingleVideo(self, video_url, youtube_choice='pytube'):
        print('sendSingleVideo()')
        YouTube = youtube_factory(youtube_choice)

        youtube = YouTube(video_url)
        channel_id = youtube.channel_id
        video_id = youtube.video_id
        video_author = youtube.author
        video_length = youtube.length

        if (video_length < 140):
            print(f'\t{video_author}: Vídeo {video_url} Enviando!')
            self.sendMedia(
                channel_id, video_id, video_author, video_url, youtube, 'video'
            )
        elif (video_length > 600):
            print(
                f'\t{video_author}: Vídeo {video_url} é MUITO LONGO: '
                f'{video_length} segundos. NÃO SERÁ ENVIADO!'
            )
        else:
            print(
                f'\t{video_author}: Vídeo {video_url} é meio LONGO: '
                f'{video_length} segundos. Enviando vídeo cortado.'
            )
            self.sendMedia(
                channel_id, video_id, video_author, video_url, youtube, 'cutted'
            )

        self.updateVideoIDs(channel_id, video_id)


    # ESCOLHE SE O VÍDEO SERÁ ENVIADO PARA O TWITTER
    # VÍDEO MAIS ANTIGO QUE O (HOJE MENOS O "limit_date") NÃO SERÁ ENVIADO
    # VÍDEO COM MINUTAGEM MAIOR QUE ("video_length" > 300) TAMBÉM NÃO SERÁ
    # ENVIADO
    # VÍDEO COM MINUTAGEM ENTRE
    # ( "video_length" >= 140 and "video_length" <= 300 ) SERÁ ENVIADO COM
    # CORTE DE 2 MINUTOS FEITO NO MEIO DO VÍDEO
    # VÍDEO COM MENOS DE 2 MINUTOS E 20 SEGUDOS SERÁ ENVIADO COMPLETO
    # AO FIM DA ESCOLHA, O ID DO VÍDEO É ADICIONADO NO BANCO DE DADOS NA LISTA
    # DO SEU RESPECTIVO CANAL
    # CANAIS NA TABELA "restrictedChannels" SÓ TERÃO OS VÍDEOS ENVIADOS SE A
    # PALAVRA TRAILER (E OUTRAS PALAVRAS CHAVE, VER "isRestrictedTrailer()")
    # ESTIVER NO TÍTULO DO VÍDEO
    # "ignore_channel_list" É UMA LISTA DE NOMES DE CANAIS QUE NÃO TERÃO SEUS
    # VÍDEOS ENVIADOS, MAS OS IDs DOS VÍDEOS SERÃO ADICIONADOS A
    # LISTA DE PROCESSADOS NO BANCO DE DADOS
    def sendTwitterChooser(
        self, channel_id, video_id, ignore_channel_list=[],
        youtube_choice='pytube'
    ):
        from datetime import datetime, timedelta

        is_age_error = False
        is_video_unavailable_error = False
        YouTube = youtube_factory(youtube_choice)
        video_url = self.yt_handler.getVideoURL(video_id)
        try:
            youtube = YouTube(video_url)
            video_date = youtube.publish_date.date()
            limit_date = datetime.today() - timedelta(days=3)
            video_length = youtube.length
            video_author = youtube.author
        except Exception as e:
            error_age = (
                'ERROR: Sign in to confirm your age\nThis video may be '
                'inappropriate for some users.'
            )
            error_video_unavailable = [
                'ERROR: Video unavailable\nThis video has been removed by the '
                'uploader',
                'ERROR: Vídeo indisponível\nEste vídeo foi removido pelo '
                'usuário que fez o envio',
                'ERROR: Vídeo indisponível\nEste vídeo é privado.'
            ]

            is_age_error = e.args[0] == error_age
            is_video_unavailable_error = e.args[0] in error_video_unavailable
            if not any([is_age_error, is_video_unavailable_error]):
                raise e

        is_sending = False
        if is_age_error:
            Color(
                f'\tVídeo: {video_url} contém restrição de idade. Ele será '
                f'SKIPADO e armazenado na tabela "restrictedAgeVideos".'
            ).bold().red().show()
            self.saveRestrictedAge(video_id)
        elif is_video_unavailable_error:
            Color(
                f'\tVídeo: {video_url} foi removido pelo dono. Ele será SKIPADO'
                f' e será adicionado a lista de processados.'
            ).bold().purple().show()
        elif (not self.isRestrictedTrailer(channel_id, youtube)):
            print(
                f'\t{video_author}: Vídeo {video_url} Canal está na lista de '
                f'restritos e não possui a palavra "trailer" (ou possui uma '
                f'palavra proibida) no título.'
            )
        elif (video_author in ignore_channel_list):
            print(
                f'\t{video_author}: Vídeo {video_url} - {video_author} está na '
                f'lista de ignorados. Vídeo não será enviado, mas será '
                f'adicionado a lista de processados.'
            )
        elif ( video_date < limit_date.date() ):
            print(
                f'\t{video_author}: Vídeo {video_url} é muito ANTIGO: '
                f'{video_date}.'
            )
        elif ( video_length == None or video_length == 0 ):
            # Vídeos com tamanho (length) zero são estreias (agendados)
            Color(
                f'\t{video_author}: Vídeo {video_url} é uma estreia '
                f'(vídeo ou live). Tem "{video_length}" segundos de duração.'
            ).bold().yellow().show()
            # Sai antes da função para não inserir o vídeo no banco de dados.
            # Linha "self.updateVideoIDs(channel_id, video_id)"
            return is_sending
        elif ( video_length >= 140 and video_length <= 300 ):
            print(
                f'\t{video_author}: Vídeo {video_url} é meio LONGO: '
                f'{video_length} segundos. Enviando vídeo cortado.'
            )
            self.sendMedia(
                channel_id, video_id, video_author, video_url, youtube, 'cutted'
            )
            is_sending = True
        elif ( video_length > 300 ):
            print(
                f'\t{video_author}: Vídeo {video_url} é muito LONGO: '
                f'{video_length} segundos.'
            )
        else:
            print(f'\t{video_author}: Vídeo {video_url} Enviando!')
            self.sendMedia(
                channel_id, video_id, video_author, video_url, youtube, 'video'
            )
            is_sending = True

        self.updateVideoIDs(channel_id, video_id)

        return is_sending


    # ADICIONA O ID DO VÍDEO NO BANCO DE DADOS NA LISTA DO SEU RESPECTIVO CANAL
    def updateVideoIDs(self, channel_id, video_id):
        document = self.mongo_conn.getDocumentByID(channel_id)

        yt_channel_model = YoutubeChannelsModel(**document)
        yt_channel_model.addVideoID(video_id)
        yt_channel_model.updateDocumentVideoIDs(self.mongo_conn.collection)


    # ENVIA UMA IMAGEM PARA O TWITTER
    def sendImage(self, channel_id, video_id, video_author, video_url, youtube):
        image_path = self.saveImage(video_id)
        media_id = self.loadMedia(image_path)
        message = self.getMessage(video_author, video_url, youtube, video_id)

        self.sleep(10, 1, 'Esperando Twitter processar mídia:')

        twitter_post_link = self.updateStatus(message, media_id)
        telegram_message = self.getTelegramMessage(
            video_author, youtube, twitter_post_link
        )
        self.telegram.send_message(telegram_message)


    # ENVIA UM VÍDEO PARA O TWITTER
    def sendVideo(self, channel_id, video_id, video_author, video_url, youtube):
        video_path = self.saveVideo(youtube)
        media_id = self.loadMedia(video_path)
        message = self.getMessage(video_author, video_url, youtube, video_id)

        self.sleep(10, 1, 'Esperando Twitter processar mídia:')

        twitter_post_link = self.updateStatus(message, media_id)
        telegram_message = self.getTelegramMessage(
            video_author, youtube, twitter_post_link
        )
        self.telegram.send_message(telegram_message)


    # SALVA LOCALMENTE UMA MÍDIA (THUMBNAIL OU VÍDEO) DO YOUTUBE COM BASE NO
    # "media_type" PASSADO
    # SE O "media_type" FOR DIFERENTE DE  "image" OU "video", O VÍDEO SERÁ
    # CORTADO PARA 2 MINUTOS
    def sendMedia(
        self, channel_id, video_id, video_author, video_url, youtube,
        media_type='cutted'
    ):
        if (media_type.lower() == 'video'):
            media_path = self.saveVideo(youtube)
        elif (media_type.lower() == 'image'):
            media_path = self.saveImage(youtube)
        else:
            media_path = self.saveCuttedVideo(youtube)

        media_id = self.loadMedia(media_path)
        message = self.getMessage(video_author, video_url, youtube, video_id)

        self.sleep(10, 1, 'Esperando Twitter processar mídia:')

        twitter_post_link = self.updateStatus(message, media_id)
        telegram_message = self.getTelegramMessage(
            video_author, youtube, twitter_post_link
        )
        self.telegram.send_message(telegram_message)


    # Retorna a mensagem usada no "updateStatus()"
    def getMessage(self, video_author, video_url, youtube, video_id=None):
        if video_id is not None:
            video_url = self.yt_handler.getShortenedVideoURL(video_id)

        title = youtube.title
        message = f'Vídeo {video_author}:\n{title}.'
        message += f'\n\nLink: {video_url}'
        message += '\n\n#MarujoBot'

        # print(f'\tTítulo do Vídeo: {title}')
        Color(f'\tTítulo do Vídeo: {title}').bold().show()

        return message


    # Retorna a mensagem usada no "self.telegram.send_message()"
    def getTelegramMessage(self, video_author, youtube, twitter_post_link):
        return (
            f'Vídeo {video_author}:'
            f'\n{youtube.title}.'
            f'\n\n{twitter_post_link}'
            f'\n\n#MarujoBot'
        )


    # SALVA UMA IMAGEM LOCALMENTE
    def saveImage(self, video_id):
        import requests
        image_url = self.yt_handler.getVideoMaxResThumbURLByID(video_id)
        image_path = 'download/image.jpg'
        response = requests.get(image_url)

        with open(image_path, 'wb') as file:
            file.write(response.content)

        return image_path


    # SALVA UM VÍDEO LOCALMENTE
    # def saveVideo(self, youtube):
    #     video = youtube.streams.filter(mime_type='video/mp4',
    #                            custom_filter_functions=[lambda s: (s.resolution == '720p') or (s.resolution == '480p')])\
    #                            .first()
    #     print('\tBaixando vídeo: ', video)
    #     max_loop = 5
    #     for i in range(max_loop):
    #         try:
    #             video.download(output_path='download', filename='video')
    #             break
    #         except Exception as e:
    #             if i >= (max_loop - 1):
    #                 raise e
    #             print('\tsaveVideo(): Um erro ocorreu no download do vídeo.')
    #             print(f'\tERRO:{e}')
    #             self.sleep(10, 1, f'Aguardando para tentar novamente ({i+1})')

    #     return 'download/video.mp4'

    def saveVideo(self, youtube):
        resolutions = ['1080p', '720p', '480p']
        max_loop = 5
        for i in range(max_loop):
            try:
                resolution = resolutions[i % len(resolutions)]
                video = youtube.streams.filter(
                    mime_type='video/mp4',
                    custom_filter_functions=[
                        lambda s: (s.resolution == resolution)
                    ]
                ).first()
                # print('\tBaixando vídeo: ', video)
                Color('\tBaixando vídeo: ', video).bold().green().show()
                video.download(output_path='download', filename='video')
                break
            except Exception as e:
                if i >= (max_loop - 1):
                    raise e
                print('\tsaveVideo(): Um erro ocorreu no download do vídeo.')
                print(f'\tERRO:{e}')
                self.sleep(10, 1, f'Aguardando para tentar novamente ({i+1})')

        return 'download/video.mp4'

    # SALVA UM VÍDEO LOCALMENTE, MAS ELE E CORTADO EM
    # 2 MINUTOS (PARTE CENTRAL DO VÍDEO)
    def saveCuttedVideo(self, youtube):
        print('\tCortando vídeo...')
        from moviepy.video.io.ffmpeg_tools import ffmpeg_extract_subclip
        video_path = self.saveVideo(youtube)
        cutted_video_path = 'download/cutted.mp4'
        mid_time = (youtube.length) // 2
        start_time = mid_time - 60
        end_time = mid_time + 60

        ffmpeg_extract_subclip(
            video_path, start_time, end_time, targetname=cutted_video_path
        )

        return cutted_video_path


    # CARREGA UMA MÍDIA (IMAGEM OU VÍDEO) NO TWITTER
    # RETORNA O ID DA MÍDIA CARREGADA
    def loadMedia(self, file_path):
        max_loop = 5
        for i in range(max_loop):
            try:
                with open(file_path, 'rb') as file:
                    if ('video.mp4' in file_path or 'cutted.mp4' in file_path):
                        response = self.twitter.upload_video(
                            media=file, media_type='video/mp4',
                            media_category='tweet_video', check_progress=True
                        )
                    else:
                        response = self.twitter.upload_media(media=file)
            except Exception as e:
                if i >= (max_loop - 1):
                    raise e
                print('\tloadMedia(): Um erro ocorreu no upload da mídia.')
                print(f'\tERRO:{e}')
                self.sleep(10, 1, f'Aguardando para tentar novamente ({i+1})')

        media_id = [response['media_id']]

        return media_id


    # ENVIA UM POST NO TWITTER
    # "media_id" É O ID DA MÍDIA CARREGADA PELO "loadMedia()"
    def updateStatus(self, message, media_id):
        max_loop = 5
        for i in range(max_loop):
            try:
                response = self.twitter.update_status(status=message,
                                                      media_ids=media_id)
                break
            except Exception as e:
                if i >= (max_loop - 1):
                    raise e
                print('\tupdateStatus(): Um erro ocorreu ao enviar o tweet.')
                print(f'\tERRO:{e}')
                self.sleep(10, 1, f'Aguardando para tentar novamente ({i+1})')

        print(
            f'\tLink do tweet: https://twitter.com/GameLootNews/status/'
            f'{response["id"]}'
        )

        return f'https://vxtwitter.com/GameLootNews/status/{response["id"]}'


    # SALVA NO MONGO VIDEO_ID DE VÍDEO RESTRITO POR IDADE
    # PARA ENIVAR POSTERIORMENTE
    def saveRestrictedAge(self, video_id):
        self.mongo_conn.setCollection('restrictedAgeVideos')
        self.mongo_conn.collection.update({'_id': "1"},
                                          {'$push': {'video_ids': video_id}})

        self.mongo_conn.setCollection()

    
    # REMOVE DO MONGO VIDEO_ID DE VÍDEO RESTRITO POR IDADE
    # QUE PROVAVELMENTE JÁ FOI ENVIADO
    def removeRestrictedAge(self, video_id):
        self.mongo_conn.setCollection('restrictedAgeVideos')
        self.mongo_conn.collection.update({'_id': "1"},
                                          {'$pull': {'video_ids': video_id}})

        self.mongo_conn.setCollection()



    # PEGA DO MONGO VIDEO_ID DE VÍDEO RESTRITO POR IDADE
    def getRestrictedAge(self):
        self.mongo_conn.setCollection('restrictedAgeVideos')
        retrict_age_unsend_dict = self.mongo_conn.collection.find(
            {'_id': "1"}
        ).next()
        # retrict_age_unsend_dict.pop('_id')
        self.mongo_conn.setCollection()

        return retrict_age_unsend_dict


    # RETORNA O DICIONÁRIO ONDE AS CHAVES SÃO OS IDs DOS CANAIS
    # E OS VALORES SÃO LISTAS COM DOS IDs DOS VÍDEOS QUE SERÃO USADOS
    # PELO "sendTwitterChooser()"
    # ESSE DICIONÁRIO É USADO PARA QUE O "startSend()" POSSA CONTINUAR O
    # ENVIO DOS VÍDEOS CASO ACONTEÇA ALGUM ERRO DURANTE A EXECUÇÃO — ISSO
    # ECONOMIZA CONSULTAS NA API DO GOOGLE
    def getInWork(self):
        self.mongo_conn.setCollection('inWork')
        unsend_dict = self.mongo_conn.collection.find_one()
        if unsend_dict:
            unsend_dict.pop('_id')

        self.mongo_conn.setCollection()

        return unsend_dict


    # SALVA O PROGRESSO DO "startSend()" NA COLEÇÃO 'inWork'
    # MAIS DETALHES EM "getInWork()"
    def saveInWork(self, unsend_dict):
        self.mongo_conn.setCollection('inWork')
        self.mongo_conn.dropCollection()
        self.mongo_conn.collection.insert_one(unsend_dict)
        self.mongo_conn.setCollection()

        if '_id' in unsend_dict:
            unsend_dict.pop('_id')


    # EXCLUI A COLEÇÃO 'inWork'
    # MAIS DETALHES EM "getInWork()"
    def dropInWork(self):
        self.mongo_conn.setCollection('inWork')
        self.mongo_conn.dropCollection()
        self.mongo_conn.setCollection()


    # A partir de um unsend_dict
    # Retorna o unsend_dict sem o primeiro ID do vídeo que seria processado
    # Também retorna o ID do canal e o ID do vídeo que foi removido
    def removeFirstUnsendDict(self, unsend_dict):
        for key, value in unsend_dict.items():
            if value:
                channel_id = key
                video_id = value.pop(0)
                break


        return unsend_dict, channel_id, video_id


    # Remove do unsend_dict o primeiro ID do vídeo que seria processado
    # Adiciona o ID do vídeo a lista de vídeos processados no banco de dados
    # Remove o ID do vídeo a lista de vídeos "inWork" no banco de dados
    # Retorna o unsend_dict sem o primeiro ID do vídeo que seria processado
    def skipFirstInWork(self, unsend_dict):
        unsend_dict, channel_id, video_id = self.removeFirstUnsendDict(
            unsend_dict
        )

        document = self.mongo_conn.getDocumentByID(channel_id)
        yt_channel_model = YoutubeChannelsModel(**document)
        yt_channel_model.addVideoID(video_id)
        yt_channel_model.updateDocumentVideoIDs(self.mongo_conn.collection)

        self.saveInWork(unsend_dict)

        return unsend_dict


    # Adiciona os IDs dos vídeos não processados de um canal a lista de
    # processados, sem enviar os vídeos para o Twitter
    def skipChannelSend(self, channel_name, size_list=5):
        document = self.mongo_conn.getDocumentByName(channel_name)
        if (not document):
            print(f'Canal "{channel_name}" não encontrado')
            return

        channel_id = document['_id']
        unsend_dict = self.getChannelUnsendVideos(document, size_list)
        print("unsend_dict:", unsend_dict)
        for video_id in unsend_dict[channel_id]:
            self.updateVideoIDs(channel_id, video_id)


    # Adiciona os IDs dos vídeos não processados de uma LISTA de canais a
    # lista de processados, sem enviar os vídeos para o Twitter
    def skipChannelsSend(self, channel_name_list, size_list=5):
        if type(channel_name_list) == list:
            for channel_name in channel_name_list:
                self.skipChannelSend(channel_name, size_list)
        else:
            raise f"channel_name_list não é uma lista, é do tipo {type(channel_name_list)}"


    # GERENCIA O ENVIO DE VÍDEOS PARA O TWITTER
    # A CONSULTA É FEITA PRIMEIRAMENTE NO MONGODB NA COLEÇÃO 'inWork'
    # CASO NÃO EXISTA VIDEOS PARA SER ENVIADO NO 'inWork'
    # OS VÍDEOS SERÃO BUSCADOS NA API DO GOOGLE
    def startSend(
        self, size_list=5, document=None, skip_first=False,
        ignore_channel_list=[], youtube_choice='pytube'
    ):
        unsend_dict = self.getInWork()
        if unsend_dict:
            print(f"Continuando Trabalho Inacabado...\n{unsend_dict}")
            if skip_first:
                print(f"Pulando primeiro vídeo...")
                self.skipFirstInWork(unsend_dict)
        elif document:
            unsend_dict = self.getChannelUnsendVideos(document, size_list)
        else:
            print('startSend() -> getAllUnsendVideos() — VÍDEOS NOVOS:')
            unsend_dict = self.getAllUnsendVideos(size_list)

        print('\nTotal de vídeos para processar:',
              sum([len(x) for x in unsend_dict.values()]))
        unsend_dict_copy = deepcopy(unsend_dict)
        self.saveInWork(unsend_dict_copy)

        print('\nstartSend() -> sendTwitterChooser()')
        total_videos = sum([len(videos) for videos in unsend_dict.values()])
        order_current_video = 0
        brasil_timezone = timezone('America/Sao_Paulo')
        for key, value in unsend_dict.items():
            print(key, value)
            for video_id in value:
                order_current_video += 1
                str_datetime_now = datetime.now(
                    tz=brasil_timezone
                ).strftime('%d/%m/%Y %H:%M:%S')
                Color(
                    f'Vídeo {order_current_video} de {total_videos}'
                    f' - {str_datetime_now}'
                ).bold().dark_cyan().show()
                is_sleep = self.sendTwitterChooser(
                    key, video_id, ignore_channel_list=ignore_channel_list,
                    youtube_choice=youtube_choice
                )
                unsend_dict_copy[key].remove(video_id)
                self.saveInWork(unsend_dict_copy)

                if (is_sleep):
                    self.sleep(
                        1, 1,'Tweet enviado. Aguardando para enviar o próximo:'
                    )
                else:
                    self.sleep(
                        1, 1, 'Aguardando para enviar o próximo tweet:'
                    )

            print()
        self.dropInWork()
        print("\n startSend() Terminou!!!")

        return unsend_dict